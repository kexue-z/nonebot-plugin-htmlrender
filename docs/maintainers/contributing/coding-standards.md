---
title: 编码规范
description: Python、异步模型、测试与可观测性的协作规范
icon: lucide/code-2
status: new
tags:
  - Maintainers
  - Standards
---

# 编码规范

## 总则

1. 优先保证行为正确与可回归验证。
2. 优先写“可读、可测、可维护”的代码。
3. API 兼容层变更必须有明确迁移说明。
4. 当局部规则冲突时，优先保持同一文件/模块的一致性。
5. 不通过 `type: ignore`、全局 lint 排除或吞掉异常来隐藏本次变更引入的诊断。

## 目录与文件组织

- 目录按依赖层组织（`application` / `rendering` / `preparation` / `resources` / `adapters` / `bootstrap`），避免按“代码类型”堆目录；
- 文件尽量保持“单一概念”，避免一个文件同时承担多个无关职责；
- 测试目录按插件实现分类维护，不把浏览器相关 case 统一堆放。

## Python 与工具链

- Python 版本与依赖以 `pyproject.toml` 为准。
- 支持版本：Python 3.10–3.14。
- 格式化：`ruff format`；CI 使用 `ruff format --check` 验证，不修改工作区。
- Lint：`ruff check`
- 类型检查：`basedpyright` + `ty`，并对 `py.typed` 公共面运行 package verifytypes
- 测试：`pytest` + `pytest-cov`

提交前至少通过：

```bash
make ruff-format
make ruff-format-check
make ruff-check
make typecheck
make ty
make test-ci
```

- 新代码使用当前仓库的类型表达方式，不为某一个检查器制造专用的公开 API。
- `ruff format` 与自动修复只用于生成有意提交的变更；合并门禁必须使用非修改模式。
- 更新依赖时通过 `uv` 修改项目元数据并刷新 `uv.lock`，保持 `uv sync --locked` 可重现。

## 异步与并发规范

- 上层协作语义使用 `anyio`；
- 对 Playwright/subprocess 这类 asyncio 原生能力，允许在实现层保持兼容调用；
- 避免模块级全局状态竞争，涉及共享状态需显式加锁；
- 并发路径必须有测试覆盖（成功、失败、超时、取消）。

## Application 与 Provider 规范

- 跨引擎能力先进入 request/use-case/port；专属能力通过 typed Capability 暴露；
- 核心层不依赖具体 Provider adapter；
- Provider 与资源服务只通过 composition 注入依赖，不读取全局配置；
- 资源解析策略变更需同步更新用户文档与迁移文档。

## 日志与可观测性规范

- 错误日志必须包含上下文（操作名、Provider ID、稳定错误类别）；
- Sentry/Prometheus 为可选能力，缺失时应有本地可观测回退（如 debug 日志）；
- 避免在高频路径打无意义 debug，必要时加开关或采样。

## 测试规范

- 按实现模块组织测试，不按“工具类别”堆叠；
- 需要真实浏览器的测试使用 `@pytest.mark.requires_browser`；
- 非浏览器单元测试默认应可在 CI profile 运行；
- 并发与生命周期测试必须覆盖“资源释放”路径；
- bugfix 先提供能在修复前失败的回归测试；新 Provider 同时覆盖 SDK、通用 executor 与 typed Capability；
- 不依赖测试执行顺序、共享进程全局状态或外部网络；确需外部服务的 case 放入明确的 smoke 层；
- 插件入口、元数据或依赖变化必须通过 Python 3.10–3.14 的 `noneload` 加载矩阵。

## 验证分层

| 层级 | 必须验证的行为 | 典型入口 |
| --- | --- | --- |
| 静态质量 | Ruff format/check、`basedpyright`、`ty` | `make ruff-format-check ruff-check typecheck ty` |
| 单元与集成 | 非浏览器 pytest；CI 额外采集 coverage | `make test-ci` / CI `Coverage` |
| 插件加载 | 隔离安装、NoneBot import/load、元数据与配置 | CI `noneload` matrix |
| 分发包 | wheel + sdist 可构建，metadata 可被 pinned `twine` 解析 | `make build-artifacts` |
| 文档 | 链接、引用与配置通过 strict build | `make docs-build` |
| 本地浏览器 | 需要 Chromium 的 Playwright 行为 | `make install-browser && make test-local` |
| 远程浏览器 | Docker 多容器、WebSocket 与资源可达性 | `make remote-smoke` |

浏览器和 Docker smoke 是条件门禁：只要改动触及页面生命周期、Playwright transport、资源解析、Filehost、模板注入或容器配置，就应运行对应层，而不是仅凭单元测试判断。

## 文档同步规范

以下变更必须同步文档：

- 对外 API 行为变更
- 配置项新增/重命名/弃用
- 架构分层或生命周期变更
- CI/CD 策略调整
- 发布、版本或包元数据策略调整

推荐同时更新：

- `docs/users/`（用户视角）
- `docs/maintainers/`（维护者视角）
