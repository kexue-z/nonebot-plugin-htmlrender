---
title: 参考手册
description: 配置字段、公共 API、类型、生命周期与错误契约
icon: lucide/code-xml
---

# 参考手册

参考手册用于定点查阅，不提供线性教程。先确定要查询的是运行配置还是 Python调用面，再进入对应分支；具体任务步骤见[指南](../guides/index.md)。

## 定位入口

| 需要查阅 | 入口 |
| --- | --- |
| 对象、流程和后端术语 | [术语表](glossary.md) |
| 完整配置树和部署字段 | [配置总览](../configuration/index.md) |
| 公共函数、request、结果与错误 | [渲染 API](rendering.md) |
| 系统分层和依赖方向 | [分层架构](../extensions/architecture.md) |

## 配置参考

| 入口 | 内容 |
| --- | --- |
| [配置总览](../configuration/index.md) | 完整 `render` 配置树和各专题入口 |
| [`.env` 配置](../configuration/dotenv.md) | dotenv 映射、加载优先级与常见后端示例 |
| 核心配置 | [启动与生命周期](../configuration/lifecycle.md) · [资源与访问策略](../configuration/resources.md) · [可选依赖与可观测性](../configuration/observability.md) |
| [HTML 后端](../configuration/providers/index.md) | [Playwright](../configuration/providers/playwright.md) · [HTMLKit](../configuration/providers/htmlkit.md) · [Takumi](../configuration/providers/takumi.md) |
| [Graphics 后端](../configuration/graphics/index.md) | [Pillow](../configuration/graphics/pillow.md) · [Skia](../configuration/graphics/skia.md) |

## API 参考

| 入口 | 内容 |
| --- | --- |
| [渲染 API](rendering.md) | 通用函数、request、Renderer、类型化产物与执行错误 |
| [Preparation 与资源 API](preparation.md) | `prepare_*`、`PreparedHtml`、资源辅助函数 |
| [Application API](application.md) | 默认对象图、startup、probe、close 与 admission |
| [Capability 参考](capabilities.md) | RasterScene、Playwright、Takumi 与 typed extension 属性 |
