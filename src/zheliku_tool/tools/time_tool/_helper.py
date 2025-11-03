from __future__ import annotations

import inspect
import logging
import os
import site
import sysconfig
from pathlib import Path

__all__ = [
    "_safe_src_info",
    "_ensure_dir",
    "_find_caller_src_path",
    "_find_caller_frame",
    "_apply_env_enable",
    "_apply_env_level",
]

def _package_root() -> Path | None:
    """
    尝试定位本包的根目录（.../zheliku_tool）。
    若未找到，返回 None。
    """
    here = Path(__file__).resolve()
    for p in [here] + list(here.parents):
        # 约定：包根目录名为 zheliku_tool，并且包含 __init__.py
        if p.name == "zheliku_tool" and (p / "__init__.py").exists():
            return p
    return None


def _safe_src_info(func):
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
        pass


def _stdlib_dirs() -> set[Path]:
    res: set[Path] = set()
    try:
        paths = sysconfig.get_paths()
        for k in ("stdlib", "platstdlib"):
            v = paths.get(k)
            if v:
                res.add(Path(v).resolve())
    except Exception:
        pass
    try:
        for p in site.getsitepackages():
            res.add(Path(p).resolve())
    except Exception:
        pass
    return res


def _find_caller_src_path() -> Path:
    this_file = Path(__file__).resolve()
    stdlib_dirs = _stdlib_dirs()
    pkg_root = _package_root()

    stack = inspect.stack()
    try:
        for fi in stack:
            fpath = Path(fi.filename).resolve()
            if fpath == this_file or fpath.name == "contextlib.py":
                continue
            try:
                if any(str(fpath).startswith(str(d)) for d in stdlib_dirs):
                    continue
            except Exception:
                pass

            # 关键：跳过整个 zheliku_tool 包目录（源码运行情况下）
            if pkg_root is not None:
                try:
                    if str(fpath).startswith(str(pkg_root)):
                        continue
                except Exception:
                    pass

            return fpath
    finally:
        del stack
    return this_file


def _find_caller_frame() -> tuple[Path, str, int]:
    this_file = Path(__file__).resolve()
    stdlib_dirs = _stdlib_dirs()
    pkg_root = _package_root()

    stack = inspect.stack()
    try:
        for fi in stack:
            fpath = Path(fi.filename).resolve()
            if fpath == this_file or fpath.name == "contextlib.py":
                continue
            try:
                if any(str(fpath).startswith(str(d)) for d in stdlib_dirs):
                    continue
            except Exception:
                pass

            # 关键：跳过整个 zheliku_tool 包目录（源码运行情况下）
            if pkg_root is not None:
                try:
                    if str(fpath).startswith(str(pkg_root)):
                        continue
                except Exception:
                    pass

            module_name = fi.frame.f_globals.get("__name__", "<unknown>")
            line = int(fi.lineno or -1)
            return fpath, module_name, line
    finally:
        del stack
    return this_file, __name__, -1


def _apply_env_enable(default: bool) -> bool:
    # 兼容多别名：TIME_LOG_* / TIMER_LOG_* / TIMER_*
    for key in ("TIME_LOG_ENABLE", "TIMER_LOG_ENABLE", "TIMER_ENABLE"):
        val = os.getenv(key)
        if val is not None:
            return val.strip() not in {"0", "false", "False", ""}
    return default


def _apply_env_level(default: int) -> int:
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    for key in ("TIME_LOG_LEVEL", "TIMER_LOG_LEVEL", "TIMER_LEVEL"):
        val = os.getenv(key)
        if val:
            return mapping.get(val.upper(), default)
    return default
