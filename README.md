# ⏱️ zheliku-tool

> 🔧 高精度 Python 函数计时与日志记录工具
> 基于标准库 `logging` 实现，兼容同步/异步函数、上下文管理器与滚动日志，
> 支持环境变量开关、loguru 风格格式、跨平台使用。

---

## 🌟 功能概述

`zheliku-tool` 提供了一个轻量级的计时装饰器与上下文管理器 `TimeLogger`，
让你可以一行代码轻松记录任意函数或代码块的执行耗时。

特点：

* ✅ 同步、异步函数统一支持
* ✅ 上下文管理器 (`with` / `async with`)
* ✅ 日志格式与 [loguru](https://github.com/Delgan/loguru) 兼容，带毫秒时间
* ✅ 自动创建日志目录，支持滚动文件
* ✅ 可通过环境变量一键开关
* ✅ 支持自定义文件名、日志目录与等级
* ✅ 提供片段计时器与函数式 API
* ✅ 无外部依赖，仅使用 Python 标准库

---

## 📦 安装

```bash
# 使用 uv（推荐）
uv add zheliku-tool

# 或使用 pip
pip install zheliku-tool
```

安装后导入：

```python
from zheliku_tool import TimeLogger, time_log
```

---

## 🧭 快速开始

### ✅ 1. 装饰器用法

```python
from zheliku_tool import TimeLogger


@TimeLogger(log_file="run.log")
def preprocess(data):
    # 模拟耗时计算
    import time;
    time.sleep(0.02)
    return [d ** 2 for d in data]


preprocess([1, 2, 3])
```

日志输出示例（默认格式）：

```
2025-11-03 15:00:21.512 | INFO     | __main__.preprocess:7 - Ran preprocess in 20.132 ms (module=__main__, file=example.py, abs='/path/example.py', line=7, pid=3901, thread=MainThread)
```

---

### ✅ 2. 异步函数

```python
import asyncio
from zheliku_tool import TimeLogger


@TimeLogger(log_file="async.log", level=logging.DEBUG)
async def fetch_data():
    await asyncio.sleep(0.01)
    return "done"


asyncio.run(fetch_data())
```

---

### ✅ 3. 上下文管理器

```python
from zheliku_tool import TimeLogger

with TimeLogger(logger_name="load_stage", log_file="stages.log"):
    # 一段代码的耗时
    sum(i * i for i in range(10_000))
```

异步上下文同理：

```python
async with TimeLogger(logger_name="async_stage", log_file="stages.log"):
    await asyncio.sleep(0.05)
```

---

### ✅ 4. 函数式上下文 API（更简洁）

```python
from zheliku_tool import time_log

with time_log("evaluate", log_file="run.log"):
    result = sum(range(1000))
```

等价于：

```python
with TimeLogger(logger_name="evaluate", log_file="run.log"):
    result = sum(range(1000))
```

---

### ✅ 5. 手动片段计时（代码内部多段耗时）

```python
from zheliku_tool import TimeLogger


def train_step():
    seg = TimeLogger.start("train")
    # 执行部分任务
    import time;
    time.sleep(0.03)
    elapsed = seg.stop()
    print(f"train_step 耗时 {elapsed:.2f} ms")
```

---

## ⚙️ 参数说明

| 参数名            | 类型                    | 默认值                   | 说明                                            |                      |
|----------------|-----------------------|-----------------------|-----------------------------------------------|----------------------|
| `level`        | `int`                 | `logging.INFO`        | 日志等级（支持 `DEBUG/INFO/WARNING/ERROR`）           |                      |
| `enable`       | `bool`                | `True`                | 是否启用计时，`False` 时直接调用函数不记录                     |                      |
| `log_dir`      | `str \| Path`         | `None`                | 日志目录（未提供时自动取函数所在文件夹）                          |
| `log_file`     | `str \| Path` | `None`                | 日志文件路径，可相对/绝对                                 |
| `extra_msg`    | `str`                 | `None`                | 附加备注文本                                        |                      |
| `fmt`          | `str`                 | 内置默认                  | `logging` 输出格式                                |                      |
| `datefmt`      | `str`                 | `"%Y-%m-%d %H:%M:%S"` | 时间格式                                          |                      |
| `logger_name`  | `str`                 | `None`                | 自定义 logger 名（默认 `<module>.<qualname>:<line>`） |                      |
| `rotate`       | `bool`                | `False`               | 是否使用滚动日志                                      |                      |
| `max_bytes`    | `int`                 | `10*1024*1024`        | 滚动阈值（字节）                                      |                      |
| `backup_count` | `int`                 | `3`                   | 滚动保留文件数                                       |                      |

---

## 🧩 环境变量控制

> 所有环境变量均可在运行前通过 `export` 或 `.env` 文件设置。
> 优先级高于代码参数。

| 环境变量                                                    | 说明                                |
|---------------------------------------------------------|-----------------------------------|
| `TIME_LOG_ENABLE` / `TIMER_LOG_ENABLE` / `TIMER_ENABLE` | 是否启用日志（`0`、`false` 表示关闭）          |
| `TIME_LOG_LEVEL` / `TIMER_LOG_LEVEL` / `TIMER_LEVEL`    | 设置全局日志等级，如 `DEBUG`、`INFO`、`ERROR` |

### 示例：

```bash
export TIME_LOG_ENABLE=0   # 全局关闭日志
export TIMER_LOG_LEVEL=DEBUG
```

---

## 🧰 日志落地规则

1. 如果提供 `log_file`：

    * **绝对路径**：直接使用；
    * **相对路径**：基于 `log_dir`（若提供）或源文件目录。
2. 如果未提供 `log_file`：

    * 自动生成 `<源文件同名>.log`；
    * 目录为 `log_dir` 或源文件目录。
3. 会自动创建不存在的目录。
4. 同一路径复用同一个 `FileHandler`，不会重复写入。

---

## 📖 输出格式

默认格式（可自定义）：

```
%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s - %(message)s
```

对应输出示例：

```
2025-11-03 14:59:01.512 | INFO     | mymodule.train:42 - Ran train in 14.832 ms (module=mymodule, file=train.py, abs='/project/train.py', line=42, pid=1234, thread=MainThread)
```

---

## 🚀 高级用法

### 🔄 滚动日志

自动切分日志文件，防止文件过大：

```python
@TimeLogger(log_file="pipeline.log", rotate=True, max_bytes=1024 * 100, backup_count=5)
def pipeline():
    ...
```

---

### 🔍 临时禁用

```python
@TimeLogger(enable=False)
def quick_func():
    pass  # 不会产生日志
```

---

### 🔧 动态控制（环境变量）

无需改代码，运行前即可启用/禁用：

```bash
TIME_LOG_ENABLE=0 uv run python your_script.py
```

---

### 🧠 线程/进程安全性

* 日志文件写入使用标准库 `FileHandler`；
* 同一 logger 不会重复绑定；
* 可在多线程下安全使用（每条日志独立写入）。

---

## 🧪 单元测试覆盖（pytest）

完整测试文件见 `tests/test_time_tool.py`，包括：

* 同步/异步装饰器
* 同步/异步上下文
* 路径解析
* 滚动日志
* 环境变量开关
* 重复 handler 检测
* 片段计时器
* 函数式上下文管理

运行测试：

```bash
uv run pytest -v
```

---

## 📜 许可证

MIT License © 2025 [zheliku](https://github.com/zheliku)

