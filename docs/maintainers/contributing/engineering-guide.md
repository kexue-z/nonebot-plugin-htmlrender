---
title: 工程协作与规范
description: 0.8 仓库结构、工作流与交付门禁
icon: lucide/folder-git-2
---

# 工程协作与规范

## 仓库结构

```text
nonebot_plugin_htmlrender/
├─ api/                 # 顶层便捷函数与默认 Application
├─ application/         # Application、Renderer、use cases、bindings
├─ rendering/           # request、artifact、error、Capability、ports
├─ preparation/         # 中立 PreparedHtml pipeline
├─ resources/           # 资源 contracts / service
├─ providers/           # Provider SDK 与 discovery
├─ adapters/
│  ├─ playwright/       # 浏览器 Provider
│  ├─ takumi/           # native Provider
│  ├─ resources/        # filesystem/package/remote/filehost adapters
│  ├─ templates/        # Jinja adapter
│  └─ observability/    # Sentry/Prometheus adapters
└─ bootstrap/           # NoneBot composition root
```

目录按依赖方向而非工具类型组织。核心 contracts 不导入 adapters/bootstrap；
新的跨层例外必须先修正抽象，不增加 architecture allowlist。

## 工作流入口

开始前以 `Makefile` 为准：

| 命令 | 用途 |
| --- | --- |
| `make prepare` | 同步全部 extras/groups 并安装 hooks |
| `make check` | format check、lint、两套类型检查和 CI profile tests |
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
4. 同步 characterization/regression tests、用户文档和维护者文档。
5. 按影响面执行静态、单元、真实引擎、远程和分发验证。

## 提交门禁

仓库使用 `prek`：

```bash
uv tool install prek
prek install
prek install --hook-type commit-msg
prek run --all-files
```

提交前至少运行 `make check`；包含文档时运行 `make docs-build`；影响引擎运行时
或资源 transport 时运行对应 smoke。

## 完成标准

- 实现完整，无临时兼容壳、全局 provider seam 或未消费的接口；
- Ruff、basedpyright、ty 与相关 pytest 通过；
- coverage 保持门槛；
- examples 与 Python 代码块跟随公共 API；
- 非 migration 文档不再描述已删除契约；
- build artifacts 与所需真实 Provider smoke 通过。

详细规则见 [编码规范](coding-standards.md)、[测试矩阵](../quality/testing-matrix.md)
和 [发布流程](../quality/release-process.md)。
