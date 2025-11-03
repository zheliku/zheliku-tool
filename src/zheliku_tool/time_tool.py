# time_tool.py
from __future__ import annotations

import inspect
import logging
import os
import threading
import time
from contextlib import ContextDecorator, contextmanager
from dataclasses import dataclass
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
    TypeVar,
    Union,
    overload,
    Coroutine,
)

__all__ = ["TimeLogger", "time_log"]

F = TypeVar("F", bound=Callable[..., Any])


# --- helpers -----------------------------------------------------------------

def _safe_src_info(func: Callable) -> tuple[Path, int]:
    """Best-effort 获取源文件路径与起始行号。失败时返回 <unknown>, -1。"""
    try:
        src_file = inspect.getsourcefile(func) or inspect.getfile(func)
        src_path = Path(src_file).resolve()
    except Exception:
        src_path = Path("<unknown>")
    try:
        _, start_line = inspect.getsourcelines(func)
    except OSError:
        start_line = -1
    return src_path, start_line


def _ensure_dir(p: Path) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # 目录创建失败时交给 logging.FileHandler 抛错即可
        pass


# --- core --------------------------------------------------------------------

class TimeLogger(ContextDecorator):
    """
    计时装饰器 & 上下文管理器（同步/异步通用）。

    功能特点
    ----------
    ✅ 一行装饰器或 with/as 即可将函数运行时间写入日志；
    ✅ 支持同步、异步、函数式三种用法；
    ✅ 支持 loguru 风格的格式输出；
    ✅ 日志路径自动推断，可自定义目录/文件名；
    ✅ 可通过环境变量全局开关或调整日志等级；
    ✅ 支持滚动日志（RotatingFileHandler）；
    ✅ 完全线程安全，可并发写入。

    环境变量覆盖（优先级高于入参）
    ----------
    - TIME_LOG_ENABLE
        是否启用日志，"0"、"false"、"False" 视为关闭
    - TIME_LOG_LEVEL
        日志级别，可为 DEBUG / INFO / WARNING / ERROR / CRITICAL

    日志路径规则
    ----------
    - 若提供 `log_file`：
        * 绝对路径：直接使用；
        * 相对路径：以 `log_dir`（若有）或函数源文件目录为基。
    - 未提供 `log_file`：
        * 文件名为 "<源文件同名>.log"；
        * 目录为 `log_dir`（若有）或源文件目录。
    - 目录会自动创建。

    上下文管理器示例
    ----------
        with TimeLogger(logger_name="load_stage", log_file="run.log"):
            load_data()

        async with TimeLogger(logger_name="aio_step", log_dir="logs"):
            await fetch()

    """

    DEFAULT_LOG_LEVEL = logging.INFO
    DEFAULT_LOG_ENABLE = True
    DEFAULT_LOG_DIR: Optional[Path] = None
    DEFAULT_LOG_FILE: Optional[Path] = None
    DEFAULT_MESSAGE: Optional[str] = None
    DEFAULT_FMT = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s - %(message)s"
    DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

    def __init__(
            self,
            *,
            level: int = DEFAULT_LOG_LEVEL,
            enable: bool = DEFAULT_LOG_ENABLE,
            log_dir: Optional[Union[str, Path]] = DEFAULT_LOG_DIR,
            log_file: Optional[Union[str, Path]] = DEFAULT_LOG_FILE,
            extra_msg: Optional[str] = DEFAULT_MESSAGE,
            fmt: Optional[str] = DEFAULT_FMT,
            datefmt: Optional[str] = DEFAULT_DATEFMT,
            # 进阶
            logger_name: Optional[str] = None,
            rotate: bool = False,
            max_bytes: int = 10 * 1024 * 1024,
            backup_count: int = 3,
    ) -> None:
        self.level = self._apply_env_level(level)
        self.enable = self._apply_env_enable(enable)
        self.user_log_dir = Path(log_dir) if log_dir is not None else None
        self.user_log_file = Path(log_file) if log_file is not None else None
        self.extra_msg = extra_msg
        self.fmt = fmt
        self.datefmt = datefmt
        self.user_logger_name = logger_name
        self.rotate = rotate
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # 运行期填充（decorator/context manager 共用）
        self._ctx_logger: Optional[logging.Logger] = None
        self._ctx_log_path: Optional[Path] = None
        self._ctx_label: Optional[str] = None
        self._ctx_src_path: Path = Path("<unknown>")
        self._ctx_start_line: int = -1
        self._ctx_module: str = ""
        self._ctx_t0_ns: Optional[int] = None

    # ---- 环境变量覆盖 -------------------------------------------------------

    @staticmethod
    def _apply_env_enable(default: bool) -> bool:
        val = os.getenv("TIME_LOG_ENABLE")
        if val is None:
            return default
        return val.strip() not in {"0", "false", "False", ""}

    @staticmethod
    def _apply_env_level(default: int) -> int:
        val = os.getenv("TIME_LOG_LEVEL")
        if not val:
            return default
        mapping = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return mapping.get(val.upper(), default)

    # ---- 路径 & logger ------------------------------------------------------

    def _resolve_log_path(self, func: Optional[Callable]) -> Path:
        """
        若 func 为 None（上下文管理器场景），将尝试使用调用点文件；
        调用点不可得时退回到当前文件同目录的 default.log。
        """
        # 优先函数
        if func is not None:
            src_path, _ = _safe_src_info(func)
        else:
            # 上下文管理器：尝试从调用栈取一帧
            frame = inspect.currentframe()
            caller_file: Optional[str] = None
            while frame:
                info = inspect.getframeinfo(frame)
                # 跳过本模块内部帧
                if info.filename and Path(info.filename).name != Path(__file__).name:
                    caller_file = info.filename
                    break
                frame = frame.f_back
            if caller_file:
                src_path = Path(caller_file).resolve()
            else:
                # 兜底：写到当前模块目录 default.log
                src_path = Path(__file__).resolve()

        if self.user_log_file:
            lf = self.user_log_file
            if lf.is_absolute():
                return lf
            base = self.user_log_dir or src_path.parent
            return (base / lf).resolve()

        default_name = f"{src_path.stem}.log"
        if self.user_log_dir:
            return (self.user_log_dir / default_name).resolve()
        return (src_path.parent / default_name).resolve()

    def _get_logger(self, *, log_path: Path, logger_name: str) -> logging.Logger:
        logger = logging.getLogger(logger_name)
        logger.setLevel(self.level)
        logger.propagate = False

        # 检查是否已有绑定该文件的 handler
        need_new = True
        for h in list(logger.handlers):
            if isinstance(h, logging.FileHandler):
                try:
                    if Path(getattr(h, "baseFilename", "")).resolve() == log_path:
                        need_new = False
                        break
                except Exception:
                    pass

        if need_new:
            _ensure_dir(log_path)
            if self.rotate:
                fh: logging.Handler = RotatingFileHandler(
                    log_path, maxBytes=self.max_bytes, backupCount=self.backup_count, encoding="utf-8"
                )
            else:
                fh = logging.FileHandler(log_path, encoding="utf-8")

            fmt = logging.Formatter(self.fmt, datefmt=self.datefmt)
            fh.setFormatter(fmt)
            fh.setLevel(self.level)
            logger.addHandler(fh)
        return logger

    # ---- 装饰器入口 ---------------------------------------------------------

    @overload
    def __call__(self, func: F) -> F:
        ...

    @overload
    def __call__(self, func: Callable[..., Awaitable[Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
        ...

    def __call__(self, func: Callable[..., Any]):  # type: ignore[override]
        # 预解析函数上下文
        src_path, start_line = _safe_src_info(func)
        module_name = func.__module__
        qualname = getattr(func, "__qualname__", getattr(func, "__name__", "unknown"))
        display_name = getattr(func, "__name__", "unknown")

        log_path = self._resolve_log_path(func)
        logger_name = self.user_logger_name or f"{module_name}.{qualname}:{start_line}"

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not self.enable:
                    return await func(*args, **kwargs)
                logger = self._get_logger(log_path=log_path, logger_name=logger_name)
                t0 = time.perf_counter_ns()
                try:
                    return await func(*args, **kwargs)
                finally:
                    t1 = time.perf_counter_ns()
                    elapsed_ms = (t1 - t0) / 1_000_000.0
                    extra = f" | {self.extra_msg}" if self.extra_msg else ""
                    thread_name = threading.current_thread().name
                    logger.log(
                        self.level,
                        (
                            f"Ran {display_name} in {elapsed_ms:.3f} ms"
                            f" (module={module_name}, file={src_path.name}, "
                            f"abs='{src_path}', line={start_line}, pid={os.getpid()}, thread={thread_name}){extra}"
                        ),
                    )

            return async_wrapper

        else:

            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.enable:
                    return func(*args, **kwargs)
                logger = self._get_logger(log_path=log_path, logger_name=logger_name)
                t0 = time.perf_counter_ns()
                try:
                    return func(*args, **kwargs)
                finally:
                    t1 = time.perf_counter_ns()
                    elapsed_ms = (t1 - t0) / 1_000_000.0
                    extra = f" | {self.extra_msg}" if self.extra_msg else ""
                    thread_name = threading.current_thread().name

                    logger.log(
                        self.level,
                        (
                            f"Ran {display_name} in {elapsed_ms:.3f} ms"
                            f" (module={module_name}, file={src_path.name}, "
                            f"abs='{src_path}', line={start_line}, pid={os.getpid()}, thread={thread_name}){extra}"
                        ),
                    )

            return wrapper

    # ---- 上下文管理器（sync / async） --------------------------------------

    def __enter__(self):
        """同步 with 支持。"""
        self._ctx_label = self.user_logger_name or "TimeLogger.ctx"
        # 尝试用调用点解析 log_path
        self._ctx_log_path = self._resolve_log_path(func=None)
        self._ctx_logger = self._get_logger(log_path=self._ctx_log_path, logger_name=self._ctx_label)
        self._ctx_module = __name__
        self._ctx_src_path = self._ctx_log_path.parent / self._ctx_log_path.name  # 仅用于占位打印
        self._ctx_start_line = -1
        if self.enable:
            self._ctx_t0_ns = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.enable or self._ctx_logger is None or self._ctx_t0_ns is None:
            return False
        t1 = time.perf_counter_ns()
        elapsed_ms = (t1 - self._ctx_t0_ns) / 1_000_000.0
        extra = f" | {self.extra_msg}" if self.extra_msg else ""
        status = "OK" if exc_type is None else f"ERR:{exc_type.__name__}"
        self._ctx_logger.log(
            self.level,
            (
                f"Ctx '{self._ctx_label}' {status} in {elapsed_ms:.3f} ms"
                f" (module={self._ctx_module}, file={self._ctx_src_path.name}, "
                f"abs='{self._ctx_src_path}', line={self._ctx_start_line}, "
                f"pid={os.getpid()}, thread=%(threadName)s){extra}"
            ),
        )
        # 不抑制异常
        return False

    async def __aenter__(self):
        """异步 with 支持。"""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        return self.__exit__(exc_type, exc, tb)

    # ---- 便捷 API -----------------------------------------------------------

    @staticmethod
    def start(name: str = "Time.segment") -> "TimeSegment":
        """
        手动片段计时器，用于函数内多段统计：
            seg = TimeLogger.start("encode")
            ... do work ...
            ms = seg.stop()
        """
        return TimeSegment(name=name)


@dataclass
class TimeSegment:
    """手动片段计时器"""
    name: str = "TimeLogger.segment"
    _t0_ns: int = -1

    def __post_init__(self):
        self._t0_ns = time.perf_counter_ns()

    def stop(self) -> float:
        t1 = time.perf_counter_ns()
        return (t1 - self._t0_ns) / 1_000_000.0


# --- 函数式上下文管理器 -------------------------------------------------------

@contextmanager
def time_log(name: str = "time_log", **kwargs: Any):
    """
    轻量函数式上下文管理器：
        with time_log("load", log_file="run.log"):
            ...
    等价于：
        with TimeLogger(logger_name=name, **kwargs):
            ...
    """
    with TimeLogger(logger_name=name, **kwargs):
        yield
