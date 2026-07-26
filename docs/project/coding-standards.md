---
title: 编码规范
description: Python、异步模型、测试与可观测性的协作规范
icon: lucide/code-2
status: new
tags:
  - Project
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
- 资源解析策略变更需同步更新使用指南、配置文档与迁移文档。

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
| 仓库级 hooks | 冲突、文件格式、元数据、拼写、源码与文档修复器 | `prek run --all-files` |
| 静态质量 | Ruff format/check、`basedpyright`、`ty` | `make ruff-format-check ruff-check typecheck ty` |
| 单元与集成 | 非浏览器 pytest；CI 额外采集 coverage | `make test-ci` / CI `Coverage` |
| 插件加载 | 隔离安装、NoneBot import/load、元数据与配置 | CI `noneload` matrix |
| 分发包 | wheel + sdist 可构建，metadata 可被 pinned `twine` 解析 | `make build-artifacts` |
| 文档 | 链接、引用与配置通过 strict build | `make docs-build` |
| 本地浏览器 | 需要 Chromium 的 Playwright 行为 | `make install-browser && make test-local` |
| 远程浏览器 | Docker 多容器、WebSocket 与资源可达性 | `make remote-smoke` |

浏览器和 Docker smoke 是条件门禁：只要改动触及页面生命周期、Playwright transport、资源解析、Filehost、模板注入或容器配置，就应运行对应层，而不是仅凭单元测试判断。

`prek` 与静态质量不是重复门禁：前者还覆盖 YAML、Markdown、拼写、冲突标记、项目元数据与 workflow，并可能执行自动修复；后者完整检查 Python 类型和测试行为。修改 workflow 时还需运行 manual `actionlint`，完整命令与重跑规则见[工程协作流程](engineering-workflow.md#prek-gates)。

## 文档同步规范

以下变更必须同步文档：

- 对外 API 行为变更
- 配置项新增/重命名/弃用
- 架构分层或生命周期变更
- CI/CD 策略调整
- 发布、版本或包元数据策略调整

按信息职责更新唯一 canonical 页面：

- `docs/start/`：首次接入与 Provider 选择；
- `docs/guides/`：完成具体任务的操作步骤与迁移；
- `docs/configuration/`：配置字段、部署、安全与排障；
- `docs/extensions/`：架构、Provider SDK 与资源管线；
- `docs/reference/`：统一术语、公共 API、类型、生命周期与错误契约；
- `docs/project/`：协作、测试、治理与发布。

站点导航不直接复制物理目录：它把页面组合为“指南、参考、原理与扩展、项目”四个顶层章节。`start/` 属于指南的入门子章；`configuration/` 中的配置字段进入参考，远程部署、安全和排障进入指南。一个 canonical 页面只能在导航中出现一次。

`docs/users/` 与 `docs/maintainers/` 只保存一个正式版本周期的旧 URL 重定向，不得重新写入正文或加入导航。

### 文档表达层级

具体语法以 [Zensical Authoring](https://zensical.org/docs/authoring/markdown/) 为准。Zensical 组件用于表达语义，不用于装饰页面：

- admonition 放置不应打断主叙事、但不能被忽略的提示、约束或风险；标题必须直接说明结论，避免只有“注意”或“提示”；
- collapsible details 收纳按症状展开的排障、兼容背景和其他可选细节，不隐藏完成当前任务必需的步骤；
- content tabs 只组织互斥实现、环境或协议；有先后关系的步骤继续使用有序列表；
- data table 表达字段映射、精确对比和测试矩阵，card grid 只用于入口页或同级导航；
- code annotations 把解释贴到配置或代码的对应行，不重复解释整个代码块；
- Mermaid 表达跨越至少三个参与者的依赖、流程或生命周期，不替代简单列表；浏览器runtime 必须使用仓库自托管的固定版本，不依赖构建或阅读时访问外部 CDN；
- button 只标记页面的主要行动入口；footnote 与 tooltip 只承载不影响主结论的出处、缩写和补充定义。

任何新增组件都必须在窄屏下保持主叙事顺序，并通过 `make docs-build` 的 strict链接、anchor、引用和配置验证。

当前 Mermaid runtime 固定为 `11.16.0`，来自 npm 发布包的`dist/mermaid.min.js`；原始 MIT 许可证位于[`docs/assets/licenses/mermaid-11.16.0.txt`](../../assets/licenses/mermaid-11.16.0.txt)。升级时使用 `npm pack mermaid@<version>` 提取发布产物，同时更新文件名、配置引用、许可证与 documentation contract 中的 SHA-256；不得改回 `mermaid@11` 这类 moving
major CDN URL。
