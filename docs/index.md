---
title: nonebot-plugin-htmlrender
description: 可插拔的 NoneBot HTML 渲染库
icon: lucide/image
---

# nonebot-plugin-htmlrender

插件把输入分成两个阶段：Preparation 将 HTML、Markdown、文本或 Jinja 模板
转换为中立的 `PreparedHtml`；配置的 Provider 再把它执行为
`RenderedImage`。Provider 专属操作通过类型化 Capability 暴露，不进入通用
渲染函数；第一方 Capability 契约从稳定的
`nonebot_plugin_htmlrender.capabilities` 包导入。

## 从这里开始

<div class="grid cards" markdown>

-   :octicons-rocket-24:{ .lg .middle } __使用渲染 API__

    ---

    安装所需 Provider，完成第一张图片，并理解类型化渲染产物。

    [:octicons-arrow-right-24: 快速开始](users/quickstart.md)

-   :octicons-arrow-switch-24:{ .lg .middle } __从 0.7 迁移__

    ---

    按公共 API、配置和资源 transport 的破坏性变化逐项迁移。

    [:octicons-arrow-right-24: v0.8 迁移指南](users/migration-v080.md)

-   :octicons-plug-24:{ .lg .middle } __开发 Provider__

    ---

    从依赖方向与 Provider SDK 开始，接入新的 HTML 渲染引擎。

    [:octicons-arrow-right-24: Provider 开发流程](maintainers/architecture/provider-development.md)

</div>

## 核心概念

| 概念 | 职责 |
| --- | --- |
| `Application` | 持有 `Renderer`、Capability catalog 与组合生命周期 |
| `Renderer` | 执行类型化 request，不感知具体引擎 |
| Preparation | 生成可移植的 `PreparedHtml` 与 `PreparedAsset` |
| Resource Service | 读取、授权、缓存并物化文档资源 |
| Provider | 校验专属配置，通过窄资源 façade 组合执行器、生命周期和 Capability |
| Graphics Capability | 通过独立 Pillow/Skia adapter 执行物理像素 `RasterScene` |
| typed artifact | 用 `RenderedImage` / `RenderedHtml` 保存结果与元数据 |

## 常用入口

- [配置与加载](users/config/core.md)
- [示例项目](users/examples.md)
- [最佳实践](users/best-practices.md)
- [安全须知](users/security.md)
- [维护者总览](maintainers/index.md)
