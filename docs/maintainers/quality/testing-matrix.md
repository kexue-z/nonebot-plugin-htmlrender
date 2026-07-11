---
title: 测试矩阵
description: Python/架构矩阵、插件加载与浏览器测试分层
icon: lucide/flask-conical
status: new
tags:
  - Maintainers
  - Testing
---

# 测试矩阵

测试不是一条重复执行的命令，而是静态检查、Python 运行时、插件加载、分发包和浏览器环境组成的分层矩阵。具体 workflow 与 artifact 入口见 [CI Actions](ci-actions.md)。

## 本地 profile

| 入口                         | profile        | `requires_browser` | 并发           | 用途                                |
| ---------------------------- | -------------- | ------------------ | -------------- | ----------------------------------- |
| `make test` / `make test-ci` | `ci`           | 跳过               | `pytest-xdist` | 快速单元与非浏览器集成测试          |
| `make test-local`            | `local`        | 执行               | 串行           | 本地 Chromium 与页面生命周期        |
| `make remote-smoke`          | Docker Compose | 执行               | 按服务拓扑     | 远程 Playwright、多容器与资源可达性 |

`make test-local` 前先运行 `make install-browser`。`make remote-smoke-build` 会强制重建镜像；普通迭代优先使用可复用缓存的 `make remote-smoke`，完成后可用 `make remote-smoke-down` 清理。

## Python 版本矩阵

项目支持 Python 3.10–3.14。`Coverage` 和 `noneload` 都覆盖完整版本范围：

| Python | pytest + coverage | `noneload` | 角色                  |
| ------ | ----------------- | ---------- | --------------------- |
| 3.10   | 是                | 是         | 最低支持版本          |
| 3.11   | 是                | 是         | 兼容版本              |
| 3.12   | 是                | 是         | 固定工具链 / 文档版本 |
| 3.13   | 是                | 是         | 新版运行时兼容        |
| 3.14   | 是                | 是         | 最新稳定版前向兼容    |

Ruff、`ty`、`basedpyright`、package 与 docs 固定在 Python 3.12，减少工具自身版本差异；这不缩小运行时支持范围，运行时兼容性由两个矩阵承担。

## CPU 架构矩阵

`Coverage` 组合 Python 与 CPU 架构，使用 `fail-fast: false` 保留完整诊断：

| Runner             | 架构  | Python                           |
| ------------------ | ----- | -------------------------------- |
| `ubuntu-latest`    | x64   | 3.10 / 3.11 / 3.12 / 3.13 / 3.14 |
| `ubuntu-24.04-arm` | arm64 | 3.10 / 3.11 / 3.12 / 3.13 / 3.14 |

每个矩阵项生成独立 coverage XML、pytest log 与 Codecov flag，并要求总覆盖率不低于 90%。某一个版本或架构失败时，不得用其他矩阵项通过来抵消。

## noneload 矩阵

[`BalconyJH/noneload`](https://github.com/BalconyJH/noneload) reusable workflow 对 `nonebot_plugin_htmlrender` 执行：

1. 在隔离环境安装当前 package；
1. 发现并 import 插件模块；
1. 让 NoneBot 实际 load 插件；
1. 检查 plugin metadata、配置模型与依赖插件要求；
1. 在任一 Python 版本失败时令 job 失败。

当前只检查核心依赖，不遍历全部 optional dependency 组合；extras 的依赖解析、backend 特有能力与真实浏览器启动分别由 package、pytest 和 smoke 层承担。`noneload` 通过不意味着渲染功能已经执行。

## 浏览器覆盖决策

| 改动范围                                                 | `test-ci` | `test-local`    | `remote-smoke`                          |
| -------------------------------------------------------- | --------- | --------------- | --------------------------------------- |
| 纯算法、类型、缓存键或无浏览器工具函数                   | 必须      | 通常不需要      | 通常不需要                              |
| Playwright page/context 生命周期、注入、截图参数         | 必须      | 必须            | 视 transport 影响                       |
| `connect_ws`、远程模板、Filehost、资源 URL、跨语言字符串 | 必须      | 建议            | 必须                                    |
| Dockerfile、Compose、浏览器版本解析                      | 必须      | 不一定          | 必须，必要时 `remote-smoke-build`       |
| 新 backend                                               | 必须      | 按 backend 能力 | 必须提供对应端到端 smoke 或说明等价环境 |

测试应覆盖成功、失败、超时、取消和资源释放。远程模式尤其不能假设浏览器能读取调用方的 `file://` filesystem。

## 分发包与文档

- 修改 `pyproject.toml`、`uv.lock`、包内资源、入口点或发布 workflow：运行 `make build-artifacts`；该 target 内部执行 `uv build --no-sources` 与 pinned `twine==6.2.0 check`；
- package resource 门禁必须在仓库外、清空 `PYTHONPATH` 后安装真实 wheel；Python 3.10–3.14 均验证 package resources 与 NoneBot/preparation smoke，Python 3.12 另验证 sdist；
- wheel/`RECORD` 检查九个内置资源均存在且非空；`[takumi]` smoke 精确校验 `takumi-py==0.2.0` 并执行真实 native PNG；
- 修改文档、MkDocs/Zensical 配置、文档依赖、Make target 或 docs workflow：运行 `make docs-build`，该 target 执行 strict build；
- 修改插件入口、metadata、config 或依赖：除单测外必须等待完整 `noneload` 矩阵；
- 修改公开行为：同步更新用户文档、回归测试和必要的迁移说明。

远程 Docker `connect_ws` smoke 覆盖 text、Markdown 相对图片、CSS 字体和模板资源，并且不得要求调用方手工提供 HTTP base URL。测试必须断言 Bot 侧 `file://` 从未作为远程文档导航目标。

## warning 与排除策略

- 主路径默认测试当前公开 API，兼容层只保留有明确价值的专测；
- `ty` 可能报告兼容层 deprecated warning；只有工具退出码为 0 且 warning 已知属于兼容契约时才可接受；
- `requires_browser` 只用于确实需要浏览器进程的 case，不得用它把普通回归测试移出 PR 快速层；
- coverage 排除必须对应不可执行或平台专用代码，并在配置中留下可审查的理由。
