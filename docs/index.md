---
title: nonebot-plugin-htmlrender
description: 可插拔的 NoneBot HTML 渲染库
icon: lucide/image
---

# nonebot-plugin-htmlrender

插件把输入分成两个阶段：Preparation 将 HTML、Markdown、文本或 Jinja 模板
转换为中立的 `PreparedHtml`；配置的 Provider 再把它执行为
`RenderedImage`。Provider 专属操作通过类型化 Capability 暴露，不进入通用
渲染函数。

## 从这里开始

=== "使用渲染 API"

    1. [快速开始](users/quickstart.md)
    2. [配置 Provider](users/config/index.md)
    3. [API 与类型化产物](users/api.md)

=== "从 0.7 迁移"

    1. [v0.8 迁移指南](users/migration-v080.md)
    2. [排障](users/troubleshooting.md)

=== "开发 Provider"

    1. [分层架构](maintainers/architecture/architecture.md)
    2. [自定义 Provider](maintainers/architecture/custom-providers.md)
    3. [Provider 开发流程](maintainers/architecture/provider-development.md)

## 核心概念

| 概念 | 职责 |
| --- | --- |
| `Application` | 持有 `Renderer`、Capability catalog 与组合生命周期 |
| `Renderer` | 执行类型化 request，不感知具体引擎 |
| Preparation | 生成可移植的 `PreparedHtml` 与 `PreparedAsset` |
| Resource Service | 读取、授权、缓存并物化文档资源 |
| Provider | 校验专属配置并组合执行器、生命周期和 Capability |
| Graphics Capability | 通过独立 Pillow/Skia adapter 执行物理像素 `RasterScene` |
| typed artifact | 用 `RenderedImage` / `RenderedHtml` 保存结果与元数据 |

## 常用入口

- [配置与加载](users/config/core.md)
- [示例项目](users/examples.md)
- [最佳实践](users/best-practices.md)
- [安全须知](users/security.md)
- [维护者总览](maintainers/index.md)
