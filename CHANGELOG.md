# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## v0.1.4 - 2025/11/04
### Fixed
- 修复包导入时额外的打印信息。
### Changed
- 更新 README.md。

## v0.1.3 - 2025/11/04
### Fixed
- 修复异步装饰器在某些情况下未正确记录调用点路径的问题。

## v0.1.2 - 2025/11/03
### Changed
- 更新作者信息。

## v0.1.1 - 2025/11/03
### Fixed
- 日志正文中的线程名不再显示为 `%(threadName)s`，改为真实线程名（`MainThread` 等）。
- `time_log()` / 上下文管理器模式下的**调用点路径**解析更稳健：排除本模块、`contextlib`、标准库与 site-packages，日志落地到用户代码目录。

## v0.1.0 - 2025/11/03
- 初始发布：同步/异步装饰器、上下文管理器、函数式 API、滚动日志、片段计时器等。
