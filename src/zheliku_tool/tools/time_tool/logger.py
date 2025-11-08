from __future__ import annotations

import inspect
import logging
import os
import threading
import time
from contextlib import ContextDecorator
from dataclasses import dataclass
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TypeVar, overload, Coroutine

from ._helper import (
    _safe_src_info,
    _ensure_dir,
    _find_caller_src_path,
    _find_caller_frame,
    _apply_env_enable,
    _apply_env_level,
)

__all__ = ["TimeLogger", "TimeSegment"]

F = TypeVar("F", bound=Callable[..., Any])


class TimeLogger(ContextDecorator):
    """
    计时装饰器 & 上下文管理器（同步/异步通用）。

    功能特点
    ----------
    - 同步/异步函数与 with/async with 统一支持
    - loguru 风格格式，带毫秒
    - 日志路径自动推断，可自定义目录/文件名
    - 环境变量全局开关/等级覆盖
    - 滚动日志（RotatingFileHandler）
    - 线程安全

    环境变量（高于入参）
    ----------
    - TIME_LOG_ENABLE / TIMER_LOG_ENABLE / TIMER_ENABLE
    - TIME_LOG_LEVEL  / TIMER_LOG_LEVEL  / TIMER_LEVEL
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
        output: str = "file",  # ✅ "file" | "console" | "both" | "none"
        log_dir: Optional[str | Path] = DEFAULT_LOG_DIR,
        log_file: Optional[str | Path] = DEFAULT_LOG_FILE,
        extra_msg: Optional[str] = DEFAULT_MESSAGE,
        fmt: Optional[str] = DEFAULT_FMT,
        datefmt: Optional[str] = DEFAULT_DATEFMT,
        # 进阶
        logger_name: Optional[str] = None,
        rotate: bool = False,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        self.level = _apply_env_level(level)
        self.enable = _apply_env_enable(enable)
        self.output = output.lower().strip()
        self.user_log_dir = Path(log_dir) if log_dir is not None else None
        self.user_log_file = Path(log_file) if log_file is not None else None
        self.extra_msg = extra_msg
        self.fmt = fmt
        self.datefmt = datefmt
        self.user_logger_name = logger_name
        self.rotate = rotate
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # ctx
        self._ctx_logger: Optional[logging.Logger] = None
        self._ctx_log_path: Optional[Path] = None
        self._ctx_label: Optional[str] = None
        self._ctx_src_path: Path = Path("<unknown>")
        self._ctx_start_line: int = -1
        self._ctx_module: str = ""
        self._ctx_t0_ns: Optional[int] = None

    # --- path & logger -------------------------------------------------------

    def _resolve_log_path(self, func: Optional[Callable], *, caller_path: Optional[Path] = None) -> Path:
        if func is not None:
            src_path, _ = _safe_src_info(func)
        else:
            src_path = caller_path or _find_caller_src_path()

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

        fmt = logging.Formatter(self.fmt, datefmt=self.datefmt)

        # --- 清理旧 handler（防止多次添加重复） ---
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

        # --- 仅文件输出 or 同时输出 ---
        if self.output in ("file", "both"):
            _ensure_dir(log_path)
            if self.rotate:
                fh: logging.Handler = RotatingFileHandler(
                    log_path, maxBytes=self.max_bytes, backupCount=self.backup_count, encoding="utf-8"
                )
            else:
                fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(self.level)
            logger.addHandler(fh)

        # --- 仅控制台输出 or 同时输出 ---
        if self.output in ("console", "both"):
            ch = logging.StreamHandler()
            ch.setFormatter(fmt)
            ch.setLevel(self.level)
            logger.addHandler(ch)

        # --- output == "none" 时不添加任何 handler ---
        return logger

    # --- decorator -----------------------------------------------------------

    @overload
    def __call__(self, func: F) -> F: ...
    @overload
    def __call__(self, func: Callable[..., Awaitable[Any]]) -> Callable[..., Coroutine[Any, Any, Any]]: ...

    def __call__(self, func: Callable[..., Any]):  # type: ignore[override]
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

    # --- context manager -----------------------------------------------------

    def __enter__(self):
        caller_path, caller_module, caller_line = _find_caller_frame()
        self._ctx_label = self.user_logger_name or "TimeLogger.ctx"
        self._ctx_log_path = self._resolve_log_path(func=None, caller_path=caller_path)
        self._ctx_logger = self._get_logger(log_path=self._ctx_log_path, logger_name=self._ctx_label)
        self._ctx_module = caller_module
        self._ctx_src_path = caller_path
        self._ctx_start_line = caller_line
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
        thread_name = threading.current_thread().name
        self._ctx_logger.log(
            self.level,
            (
                f"Ctx '{self._ctx_label}' {status} in {elapsed_ms:.3f} ms"
                f" (module={self._ctx_module}, file={self._ctx_src_path.name}, "
                f"abs='{self._ctx_src_path}', line={self._ctx_start_line}, "
                f"pid={os.getpid()}, thread={thread_name}){extra}"
            ),
        )
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        return self.__exit__(exc_type, exc, tb)

    # --- convenience ---------------------------------------------------------

    @staticmethod
    def start(name: str = "Time.segment") -> "TimeSegment":
        return TimeSegment(name=name)


@dataclass
class TimeSegment:
    name: str = "TimeLogger.segment"
    _t0_ns: int = -1
    def __post_init__(self):
        self._t0_ns = time.perf_counter_ns()
    def stop(self) -> float:
        t1 = time.perf_counter_ns()
        return (t1 - self._t0_ns) / 1_000_000.0
