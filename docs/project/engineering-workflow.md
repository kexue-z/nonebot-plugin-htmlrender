---
title: 工程协作流程
description: 0.8 仓库结构、工作流与交付门禁
icon: lucide/folder-git-2
---

# 工程协作流程

## 仓库结构

```text
nonebot_plugin_htmlrender/
├─ api/                 # 顶层便捷函数与默认 Application
├─ capabilities/        # 稳定的第一方 Provider Capability 契约与 lookup key
├─ application/         # Application、Renderer、use cases、bindings
├─ rendering/           # request、artifact、error、Capability、ports
├─ preparation/         # 中立 PreparedHtml pipeline
├─ resources/           # 资源 contracts / service
├─ providers/           # Provider SDK 与 discovery
├─ adapters/
│  ├─ htmlkit/          # litehtml/Cairo Provider
│  ├─ playwright/       # 浏览器 Provider
│  ├─ takumi/           # native Provider
│  ├─ pillow/           # RasterScene adapter
│  ├─ skia/             # RasterScene adapter
│  ├─ resources/        # filesystem/package/remote/filehost adapters
│  ├─ templates/        # Jinja adapter
│  └─ observability/    # Sentry/Prometheus adapters
└─ bootstrap/           # NoneBot composition root
```

目录按依赖方向而非工具类型组织。核心 contracts 不导入 adapters/bootstrap；新的跨层例外必须先修正抽象，不增加 architecture allowlist。

Playwright 的安装、signal 与 process helper 位于 `adapters/playwright/_support`；仓库不保留按“通用工具”命名的顶层 `utils` 兼容目录。枚举也由其领域模块拥有：资源策略在 `resources.config`，浏览器配置在 `adapters.playwright.config`，启动策略在`bootstrap.settings`。

## 工作流入口

开始前以 `Makefile` 为准：

| 命令 | 用途 |
| --- | --- |
| `make prepare` | 同步全部 extras/groups 并安装 hooks |
| `make install-prek` | 安装 `prek` 及 `pre-commit`、`commit-msg` hooks |
| `make check` | format check、lint、两套类型检查、公共 API 类型完备性和 CI profile tests |
| `make type-completeness` | 用 basedpyright 验证 `py.typed` 公共符号为 100% 完备 |
| `make test-local` | 真实本地 Chromium |
| `make remote-smoke` | 复用镜像执行远程浏览器 smoke |
| `make remote-smoke-build` | 重建镜像并执行远程 smoke |
| `make docs-build` | Zensical strict build |
| `make build-artifacts` | wheel/sdist、metadata 与隔离安装验证 |

不要绕开这些入口猜测独立命令；新增流程时先更新 Makefile 和本页。

## 变更步骤

1. 调查现有 contracts、测试与调用方。
2. 对公共接口、模块边界或生命周期变化先形成明确设计。
3. 在正确层实现，不通过全局 seam 或专属分支穿透边界。
4. 同步 characterization/regression tests，以及对应的任务指南、API 参考或项目维护文档。
5. 按影响面执行静态、单元、真实引擎、远程和分发验证。

## 提交门禁 { #prek-gates }

仓库使用 `prek` 执行 `.pre-commit-config.yaml`。首次准备环境时统一通过 Makefile安装工具与两类 Git hook：

```bash
make install-prek
```

| Stage | 触发方式 | 覆盖范围 | 检查要求 |
| --- | --- | --- | --- |
| `pre-commit` | `git commit` 或显式运行 `prek` | 冲突标记、文件结尾、项目元数据、拼写、YAML、Python、Markdown 与 workflow 静态检查 | 日常提交自动执行；PR 前必须执行全仓检查 |
| `commit-msg` | `git commit` | Conventional Commit 的 `type` | 每个本地提交；完整格式见[提交消息指南](commit-messages.md) |
| `manual` | 显式运行 | `actionlint` 及其 ShellCheck 集成 | 修改 `.github/workflows/` 或相关配置时必须执行 |

开发过程中可只检查正在编辑的文件，但这不是交付门禁：

```bash
prek run --files <path> [<path> ...]
```

发起或更新 PR 前必须执行默认 stage 的全仓检查：

```bash
prek run --all-files
```

workflow 相关变更还必须执行 manual stage：

```bash
prek run actionlint --all-files --hook-stage=manual
```

!!! warning "自动修复后必须检查并重跑"

    Ruff、Prettier、Markdownlint、Blacken Docs 和文件结尾等 hook 可能直接修改文件。首次运行因此失败并不表示可以忽略：先检查 `git diff`，确认修复符合意图，再对同一范围重新运行，直到命令不再修改文件且退出成功。不要未经审阅就暂存 hook生成的改动。

`.pre-commit-config.yaml` 是 hook、stage、执行优先级和排除规则的唯一事实来源。仓库模板与自托管的 vendored runtime 等受控产物可以被定向排除；排除只避免工具破坏生成物或第三方产物，不代表可以跳过其许可证、checksum、构建或契约测试。CI 的 `Prek` workflow 对所有变更执行默认全仓检查，并额外执行 manual `actionlint`；本地最终结果必须与这两步一致。

提交前至少运行 `make check`；包含文档时运行 `make docs-build`；影响引擎运行时或资源 transport 时运行对应 smoke。

## 完成标准

- 实现完整，无临时兼容壳、全局 provider seam 或未消费的接口；
- Ruff、basedpyright、ty 与相关 pytest 通过，type completeness 保持 100%；
- coverage 保持门槛；
- examples 与 Python 代码块跟随公共 API；
- 非 migration 文档不再描述已删除契约；
- build artifacts 与所需真实 Provider smoke 通过。

详细规则见 [编码规范](coding-standards.md)、[测试矩阵](testing.md)和 [发布流程](release.md)。
