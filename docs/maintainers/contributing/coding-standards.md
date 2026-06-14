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

## 目录与文件组织

- 目录按能力域组织（`render` / `backend` / `resources` / `utils`），避免按“代码类型”堆目录；
- 文件尽量保持“单一概念”，避免一个文件同时承担多个无关职责；
- 测试目录按插件实现分类维护，不把浏览器相关 case 统一堆放。

## Python 与工具链

- Python 版本与依赖以 `pyproject.toml` 为准。
- 格式化：`ruff format`
- Lint：`ruff check`
- 类型检查：`basedpyright` + `ty`
- 测试：`pytest` + `pytest-cov`

提交前至少通过：

```bash
make ruff-format
make ruff-check
make typecheck
make ty
make test-ci
```

## 异步与并发规范

- 上层协作语义使用 `anyio`；
- 对 Playwright/subprocess 这类 asyncio 原生能力，允许在实现层保持兼容调用；
- 避免模块级全局状态竞争，涉及共享状态需显式加锁；
- 并发路径必须有测试覆盖（成功、失败、超时、取消）。

## 渲染层（Render）规范

- 新能力优先挂接到 `render` 抽象层，再由 backend 实现；
- 不在上层直接依赖具体 backend 内部细节；
- 资源解析策略变更需同步更新用户文档与迁移文档。

## 日志与可观测性规范

- 错误日志必须包含上下文（操作名、后端、关键参数）；
- Sentry/Prometheus 为可选能力，缺失时应有本地可观测回退（如 debug 日志）；
- 避免在高频路径打无意义 debug，必要时加开关或采样。

## 测试规范

- 按实现模块组织测试，不按“工具类别”堆叠；
- 需要真实浏览器的测试使用 `@pytest.mark.requires_browser`；
- 非浏览器单元测试默认应可在 CI profile 运行；
- 并发与生命周期测试必须覆盖“资源释放”路径。

## 文档同步规范

以下变更必须同步文档：

- 对外 API 行为变更
- 配置项新增/重命名/弃用
- 架构分层或生命周期变更
- CI/CD 策略调整

推荐同时更新：

- `docs/users/`（用户视角）
- `docs/maintainers/`（维护者视角）
