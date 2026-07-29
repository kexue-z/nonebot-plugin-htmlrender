---
title: 测试矩阵
description: Python/架构矩阵、插件加载与浏览器测试分层
icon: lucide/flask-conical
status: new
tags:
  - Project
  - Testing
---

# 测试矩阵

测试不是一条重复执行的命令，而是静态检查、Python 运行时、插件加载、分发包和浏览器环境组成的分层矩阵。具体 workflow 与 artifact 入口见 [CI Actions](ci.md)。

## 测试所有权边界

仓库测试只覆盖本项目拥有的行为：输入与输出转换、组件接线、缓存和并发不变量、生命周期、错误翻译以及公开契约。第三方组件只在集成边界保留最小 smoke，用来确认当前锁定版本能够完成一次成功调用，并在必要时确认异常能被翻译到稳定边界。

不得为了覆盖率重复验证第三方库已经拥有的格式矩阵、CSS/模板语义、像素算法、子进程参数语义或原生并发正确性。适配器单测应注入或模拟第三方边界，断言本项目传入了什么、如何处理返回值以及如何释放资源；第三方自身的行为由依赖锁定、上游测试和边界 smoke 承担。覆盖率不足时应补齐未验证的项目实现，不能增加上游行为测试充数。

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

Ruff、`ty`、`basedpyright`、package 与 docs 工具固定在 Python 3.12，减少工具自身版本差异；`basedpyright.pythonVersion` 保持为最低支持版本 3.10，以便静态契约不会误用较新语法或标准库。这不缩小运行时支持范围，运行时兼容性由两个矩阵承担。

`make typecheck` 同时执行普通源码分析与`basedpyright --verifytypes nonebot_plugin_htmlrender --ignoreexternal`。后者要求`py.typed` 分发包的仓库内公共符号达到 100% type completeness；外部依赖自身缺少stub 不计入本仓库分数，但本仓库把 unknown/ambiguous 类型传播到公共签名仍会失败。

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

当前只检查核心依赖，不遍历全部 optional dependency 组合；extras 的依赖解析、Provider 专属能力与真实浏览器启动分别由 package、pytest 和 smoke 层承担。`noneload` 通过不意味着渲染功能已经执行。

## 浏览器覆盖决策

| 改动范围                                                 | `test-ci` | `test-local`    | `remote-smoke`                          |
| -------------------------------------------------------- | --------- | --------------- | --------------------------------------- |
| 纯算法、类型、缓存键或无浏览器工具函数                   | 必须      | 通常不需要      | 通常不需要                              |
| Playwright page/context 生命周期、注入、截图参数         | 必须      | 必须            | 视 transport 影响                       |
| `connect_ws`、远程模板、Filehost、资源 URL、跨语言字符串 | 必须      | 建议            | 必须                                    |
| Dockerfile、Compose、浏览器版本解析                      | 必须      | 不一定          | 必须，必要时 `remote-smoke-build`       |
| 新 Provider                                              | 必须      | 按 Provider 能力 | 必须提供对应端到端 smoke 或说明等价环境 |

测试应覆盖成功、失败、超时、取消和资源释放。远程模式尤其不能假设浏览器能读取调用方的 `file://` filesystem。

## 分发包与文档

- 修改 `pyproject.toml`、`uv.lock`、包内资源、入口点或发布 workflow：运行 `make build-artifacts`；该 target 内部执行 `uv build --no-sources` 与 pinned `twine==6.2.0 check`；
- package resource 门禁必须在仓库外、清空 `PYTHONPATH` 后安装真实 wheel；Python 3.10–3.14 均验证 package resources 与 NoneBot/preparation smoke，Python 3.12 另验证 sdist；
- wheel/`RECORD` 检查九个内置资源均存在且非空；bare-core smoke 断言 HTMLKit、Playwright、Takumi、Pillow 与 Skia 均未安装；`[htmlkit]` 与 `[takumi]` 分别校验锁定版本并执行真实 native PNG，`[pillow,skia]` 验证独立 `RasterScene` 能力；
- 修改文档、MkDocs/Zensical 配置、文档依赖、Make target 或 docs workflow：运行 `make docs-build`，该 target 执行 strict build；
- 修改插件入口、metadata、config 或依赖：除单测外必须等待完整 `noneload` 矩阵；
- 修改公开行为：同步更新使用指南或 API 参考、回归测试和必要的迁移说明。

Documentation contract 属于 pytest 门禁，而不只是站点构建：

- 非 migration README/docs/examples 禁止已删除的 0.7/alpha 契约；
- 当前公共顶层导出必须有文档覆盖；
- `render` schema 的全部 leaf 使用完整 dotted path；
- 所有 Python fence 与 examples Python 文件必须可解析；
- 顶层示例 import 必须存在于 `__all__`；
- examples 纳入 basedpyright、ty 与 Ruff 检查。

`make docs-build` 另外验证导航、链接、anchor、引用和静态站渲染，两层都必须通过。

远程 Docker `connect_ws` smoke 依次覆盖 `memory` 与 `filehost` transport 下的text、Markdown 相对图片、CSS 字体和模板资源，并且不得要求调用方手工提供 HTTP
base URL。Markdown 使用哨兵像素证明相对图片确实加载；filehost 还必须观察远程Chromium 发起的 CSS、PNG、WOFF2 请求，并验证请求头守卫、通配 CORS 和未认证403。测试必须断言 Bot 侧 `file://` 从未作为远程文档导航目标。

## warning 与排除策略

- 主路径与 examples 只测试当前公开 API；旧契约只允许出现在显式 migration 对照中；
- `ty` / basedpyright 必须零错误，包级 type completeness 必须为 100%；不得用ignore 掩盖已删除接口或公共签名中的 unknown；
- `requires_browser` 只用于确实需要浏览器进程的 case，不得用它把普通回归测试移出 PR 快速层；
- coverage 排除必须对应不可执行或平台专用代码，并在配置中留下可审查的理由。
