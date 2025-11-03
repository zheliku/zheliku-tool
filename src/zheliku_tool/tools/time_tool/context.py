from __future__ import annotations
from contextlib import contextmanager
from typing import Any
from .logger import TimeLogger

__all__ = ["time_log"]

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
