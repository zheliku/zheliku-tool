# tests/test_time_logger.py
import asyncio
import logging
import os
from pathlib import Path

import pytest

from zheliku_tool import TimeLogger, time_log

# 被测模块：根据你的包结构调整这里的导入
# 若使用 "src/yourlib/timer_tool.py" 并在 __init__.py 里导出：
# from yourlib import TimeLogger, timer_log
# 如果你是直接把文件放在项目根目录运行测试，则用下面这种相对导入：

# --------------------------
# 辅助函数
# --------------------------
def read_text(p: Path | str) -> str:
    p = Path(p)
    return p.read_text(encoding="utf-8") if p.exists() else ""

# --------------------------
# 装饰器：同步
# --------------------------
def test_sync_decorator_basic(tmp_path: Path):
    log_path = tmp_path / "sync.log"

    print(tmp_path)

    @TimeLogger(log_file=log_path, level=logging.INFO)
    def work(x, y):
        return x + y

    out = work(3, 4)
    assert out == 7
    assert log_path.exists()
    t = read_text(log_path)
    assert "Ran work in" in t
    assert "| INFO     |" in t  # 默认格式中包含 levelname
    assert "thread=MainThread" in t  # 日志中有线程名字段


# --------------------------
# 装饰器：异步
# --------------------------
@pytest.mark.asyncio
async def test_async_decorator_basic(tmp_path: Path):
    log_path = tmp_path / "async.log"

    @TimeLogger(log_file=log_path, level=logging.DEBUG)
    async def fetch(v):
        await asyncio.sleep(0.01)
        return v * 2

    res = await fetch(5)
    assert res == 10
    assert log_path.exists()
    t = read_text(log_path)
    assert "Ran fetch in" in t
    assert "| DEBUG    |" in t


# --------------------------
# 上下文管理器：同步
# --------------------------
def test_sync_context_ok(tmp_path: Path):
    log_path = tmp_path / "ctx_sync.log"
    with TimeLogger(logger_name="stage:load", log_file=log_path):
        x = sum(range(10))
        assert x == 45
    t = read_text(log_path)
    assert "Ctx 'stage:load' OK in" in t


def test_sync_context_error(tmp_path: Path):
    log_path = tmp_path / "ctx_err.log"
    with pytest.raises(ValueError):
        with TimeLogger(logger_name="boom", log_file=log_path):
            raise ValueError("bad")
    t = read_text(log_path)
    assert "Ctx 'boom' ERR:ValueError in" in t


# --------------------------
# 上下文管理器：异步
# --------------------------
@pytest.mark.asyncio
async def test_async_context_ok(tmp_path: Path):
    log_path = tmp_path / "ctx_async.log"
    async with TimeLogger(logger_name="aio:step", log_file=log_path):
        await asyncio.sleep(0.01)
    t = read_text(log_path)
    assert "Ctx 'aio:step' OK in" in t


# --------------------------
# 路径解析：log_dir + 相对 log_file
# --------------------------
def test_path_resolution_with_log_dir_and_relative_file(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rel_file = Path("my.log")

    @TimeLogger(log_dir=log_dir, log_file=rel_file)
    def f():
        return 1

    assert f() == 1
    expected = (log_dir / rel_file).resolve()
    assert expected.exists()
    t = read_text(expected)
    assert "Ran f in" in t


# --------------------------
# 路径解析：绝对 log_file 优先
# --------------------------
def test_path_resolution_with_absolute_file(tmp_path: Path):
    abs_file = (tmp_path / "abs.log").resolve()

    @TimeLogger(log_dir=tmp_path / "ignored_dir", log_file=abs_file)
    def f():
        return "ok"

    assert f() == "ok"
    assert abs_file.exists()
    t = read_text(abs_file)
    assert "Ran f in" in t


# --------------------------
# 禁用态：不应写文件
# --------------------------
def test_enable_false_no_log_written(tmp_path: Path):
    p = tmp_path / "disabled.log"

    @TimeLogger(log_file=p, enable=False)
    def f():
        return 123

    assert f() == 123
    assert not p.exists()  # 不创建文件


# --------------------------
# 环境变量覆盖：TIMER_LOG_ENABLE / TIMER_LOG_LEVEL
# --------------------------
def test_env_overrides_level_and_enable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 关闭写入
    monkeypatch.setenv("TIME_LOG_ENABLE", "0")
    p = tmp_path / "env1.log"

    @TimeLogger(log_file=p, level=logging.INFO)
    def f1():
        return "x"

    assert f1() == "x"
    assert not p.exists()

    # 开启 + 设置 DEBUG
    monkeypatch.setenv("TIME_LOG_ENABLE", "1")
    monkeypatch.setenv("TIME_LOG_LEVEL", "DEBUG")
    p2 = tmp_path / "env2.log"

    @TimeLogger(log_file=p2, level=logging.INFO)
    def f2():
        return "y"

    assert f2() == "y"
    assert p2.exists()
    t = read_text(p2)
    assert "| DEBUG    |" in t


# --------------------------
# 滚动日志：触发 .1 文件
# --------------------------
def test_rotating_file_handler_rollover(tmp_path: Path):
    p = tmp_path / "rotate.log"

    # 将 max_bytes 设极小，使第二次写入必然翻转
    dec = TimeLogger(log_file=p, rotate=True, max_bytes=1, backup_count=2)

    @dec
    def g():
        return 42

    # 两次写入
    assert g() == 42
    assert g() == 42

    # 主文件 & 第一个轮转文件都应存在
    assert p.exists()
    rotated = Path(str(p) + ".1")
    assert rotated.exists()


# --------------------------
# 无重复写入：同一次调用只写一行
# --------------------------
def test_no_duplicate_handlers(tmp_path: Path):
    p = tmp_path / "dedup.log"
    dec = TimeLogger(log_file=p, logger_name="unique")

    @dec
    def h():
        return 7

    # 调用一次 -> 只应出现一条 "Ran h in"
    assert h() == 7
    t1 = read_text(p)
    assert t1.count("Ran h in") == 1

    # 再调用一次 -> 总数应为 2
    assert h() == 7
    t2 = read_text(p)
    assert t2.count("Ran h in") == 2


# --------------------------
# TimerSegment 片段计时
# --------------------------
def test_timer_segment_basic():
    seg = TimeLogger.start("encode")
    # 模拟工作
    s = seg.stop()
    assert isinstance(s, float)
    assert s >= 0.0


# --------------------------
# 函数式上下文管理器 timer_log
# --------------------------
def test_function_style_timer_log(tmp_path: Path):
    p = tmp_path / "func_ctx.log"
    with time_log("evaluate", log_file=p, level=logging.INFO):
        _ = [i * i for i in range(100)]
    t = read_text(p)
    print(f"t: {t}")
    assert "Ctx 'evaluate' OK in" in t
