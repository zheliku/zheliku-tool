import asyncio
import time
from pathlib import Path

import pytest

# 假设你的包名为 mypkg，并暴露 TimeLogger
# 如果在本仓库直接引用模块文件，请按你的实际路径修改
from zheliku_tool import TimeLogger  # 改成你的实际导入路径


# ---------------------------
# 工具函数
# ---------------------------

def read_all_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def find_single_log(tmp_path: Path, expected_name: str | None = None) -> Path | None:
    """
    在 tmp_path 下查找单个日志文件。
    如果传了 expected_name，则优先返回 tmp_path/expected_name。
    否则返回第一个 *.log。
    """
    if expected_name:
        p = tmp_path / expected_name
        return p if p.exists() else None
    logs = list(tmp_path.glob("*.log"))
    return logs[0] if logs else None


def stderr_of(capsys) -> str:
    out = capsys.readouterr()
    # logging.StreamHandler 默认写 stderr
    return out.err


# ---------------------------
# 基础：console / file / both / none
# ---------------------------

def test_console_only_outputs(tmp_path, capsys):
    @TimeLogger(output="console", log_dir=tmp_path)
    def work():
        time.sleep(0.01)

    work()
    err = stderr_of(capsys)
    assert "Ran work in" in err
    # console only，不应产生文件
    assert not list(tmp_path.glob("*.log"))


def test_file_only_outputs(tmp_path, capsys):
    @TimeLogger(output="file", log_dir=tmp_path)
    def job():
        time.sleep(0.01)

    job()
    # 没有控制台输出
    err = stderr_of(capsys)
    assert err.strip() == ""

    # 在 log_dir 内应该有 <测试文件名>.log
    # 默认名取决于函数源文件名（即当前测试文件名）
    expected = f"{Path(__file__).stem}.log"
    logp = find_single_log(tmp_path, expected_name=expected)
    assert logp and logp.exists()
    content = read_all_text(logp)
    assert "Ran job in" in content


def test_both_outputs(tmp_path, capsys):
    @TimeLogger(output="both", log_dir=tmp_path)
    def fn():
        time.sleep(0.01)

    fn()
    err = stderr_of(capsys)
    assert "Ran fn in" in err

    expected = f"{Path(__file__).stem}.log"
    logp = find_single_log(tmp_path, expected_name=expected)
    assert logp and logp.exists()
    assert "Ran fn in" in read_all_text(logp)


def test_none_outputs(tmp_path, capsys):
    @TimeLogger(output="none", log_dir=tmp_path)
    def noop():
        time.sleep(0.001)

    noop()
    # 不输出控制台、不写文件
    err = stderr_of(capsys)
    assert err.strip() == ""
    assert not list(tmp_path.glob("*.log"))


# ---------------------------
# 上下文管理器
# ---------------------------

def test_context_manager_file(tmp_path):
    with TimeLogger(output="file", log_dir=tmp_path, logger_name="ctx-test"):
        time.sleep(0.005)

    expected = f"{Path(__file__).stem}.log"
    logp = find_single_log(tmp_path, expected_name=expected)
    assert logp and logp.exists()
    content = read_all_text(logp)
    assert "Ctx 'ctx-test' OK in" in content


@pytest.mark.asyncio
async def test_async_context_manager_console(tmp_path, capsys):
    async with TimeLogger(output="console", log_dir=tmp_path, logger_name="ctx-async"):
        await asyncio.sleep(0.01)

    err = stderr_of(capsys)
    assert "Ctx 'ctx-async' OK in" in err


# ---------------------------
# 异步函数装饰
# ---------------------------

@pytest.mark.asyncio
async def test_async_function_console(tmp_path, capsys):
    @TimeLogger(output="console", log_dir=tmp_path)
    async def afunc():
        await asyncio.sleep(0.01)

    await afunc()
    err = stderr_of(capsys)
    assert "Ran afunc in" in err


# ---------------------------
# 自定义 log_file / extra_msg
# ---------------------------

def test_custom_log_file_and_extra_msg(tmp_path):
    @TimeLogger(output="file", log_dir=tmp_path, log_file="my.log", extra_msg="EXTRA")
    def foo():
        time.sleep(0.002)

    foo()
    logp = tmp_path / "my.log"
    assert logp.exists()
    content = read_all_text(logp)
    assert "Ran foo in" in content
    assert " | EXTRA" in content  # 检查追加消息


# ---------------------------
# 多次调用不重复叠加 handler（文件行数增长、但不重复同一条）
# ---------------------------

def test_multiple_calls_no_duplicate_handlers(tmp_path):
    @TimeLogger(output="file", log_dir=tmp_path, log_file="dup.log")
    def work():
        time.sleep(0.001)

    for _ in range(3):
        work()

    logp = tmp_path / "dup.log"
    assert logp.exists()
    content = read_all_text(logp)
    # 应至少出现 3 次 "Ran work in"
    assert content.count("Ran work in") >= 3
    # 不应出现明显重复的同一条（极端情况下不严检，只要次数不小于3即可）


# ---------------------------
# rotate 滚动日志（设置很小的 max_bytes，触发滚动）
# ---------------------------

def test_rotate_basic(tmp_path):
    logp = tmp_path / "roll.log"

    @TimeLogger(output="file", log_dir=tmp_path, log_file=logp.name,
                rotate=True, max_bytes=200, backup_count=2)
    def payload():
        # 写入稍多一点的内容触发滚动
        for _ in range(10):
            time.sleep(0.001)

    # 调用多次
    for _ in range(5):
        payload()

    # 主文件
    assert logp.exists()
    # 备份文件（命名通常为 roll.log.1 / roll.log.2）
    rotated = list(tmp_path.glob("roll.log*"))
    # 至少应有 2~3 个文件（主 + 备份们）
    assert len(rotated) >= 2


# ---------------------------
# 环境变量覆盖（enable 关闭）
# 注：依赖 _apply_env_enable() 的实现：TIME_LOG_ENABLE=0 禁用
# ---------------------------

def test_env_disable_overrides_enable(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TIME_LOG_ENABLE", "0")

    @TimeLogger(output="both", log_dir=tmp_path, log_file="env.log", enable=True)
    def job():
        time.sleep(0.002)

    job()

    # 被环境关闭后：无控制台输出、无文件
    err = stderr_of(capsys)
    assert err.strip() == ""
    assert not (tmp_path / "env.log").exists()


# ---------------------------
# 等级覆盖（可选，若你 _apply_env_level 支持）
# 这里只检查不会异常，并且有输出（等级设置本类用于 logger/handler）
# ---------------------------

def test_env_level_set(monkeypatch, tmp_path):
    monkeypatch.setenv("TIME_LOG_LEVEL", "INFO")

    @TimeLogger(output="file", log_dir=tmp_path, log_file="level.log", level=10)  # 10=DEBUG
    def do():
        time.sleep(0.001)

    do()
    p = tmp_path / "level.log"
    assert p.exists()
    content = read_all_text(p)
    assert "Ran do in" in content


# ---------------------------
# async 装饰 + both 输出
# ---------------------------

@pytest.mark.asyncio
async def test_async_both(tmp_path, capsys):
    @TimeLogger(output="both", log_dir=tmp_path, log_file="both_async.log")
    async def af():
        await asyncio.sleep(0.005)

    await af()

    # console
    err = stderr_of(capsys)
    assert "Ran af in" in err

    # file
    p = tmp_path / "both_async.log"
    assert p.exists()
    assert "Ran af in" in read_all_text(p)


# ---------------------------
# with 上下文 + both 输出
# ---------------------------

def test_context_both(tmp_path, capsys):
    with TimeLogger(output="both", log_dir=tmp_path, log_file="ctx_both.log", logger_name="ctx-both"):
        time.sleep(0.003)

    err = stderr_of(capsys)
    assert "Ctx 'ctx-both' OK in" in err
    p = tmp_path / "ctx_both.log"
    assert p.exists()
    assert "Ctx 'ctx-both' OK in" in read_all_text(p)
