---
title: 术语表
description: 渲染流程、对象、后端、扩展点与结果类型的统一定义
icon: lucide/book-a
---

# 术语表

本页用于查词，不是开始使用前的必读章节。需要完成具体任务时进入[指南](../guides/index.md)；需要理解各层为何这样连接时阅读[分层架构](../extensions/architecture.md)。

## 两条渲染路径

| 路径 | 数据流 |
| --- | --- |
| HTML 渲染 | HTML、Markdown、文本或模板 → Preparation → `PreparedHtml` → `Renderer` → 所选 HTML 后端 → `RenderedImage` |
| Graphics 渲染 | `RasterScene` → 指定的 Pillow 或 Skia Capability → Graphics 后端 → `RenderedImage` |

HTML 路径一次只选择一个后端。Graphics 后端独立启用，可以与任意 HTML 后端并存，也可以在未选择 HTML 后端时单独使用。

## 运行时与生命周期

| 术语 | 定义 |
| --- | --- |
| `Application` | 一次 composition 的公共入口，聚合 `Renderer`、Preparation/Resource façade、typed extensions 与生命周期；Capability catalog 是其内部组合结构。 |
| composition | 根据配置发现后端、校验专属设置并连接核心端口与 adapter 的过程；结果是一套可启动和关闭的对象图。 |
| composition root | 唯一允许读取 NoneBot 配置、发现实现并完成依赖接线的 bootstrap 边界。 |
| `Renderer` | 执行跨 HTML 后端可移植 request 的稳定 façade；不暴露页面、node 或 native 对象。 |
| startup | composition 的启动策略：`off` 延迟启动，`warmup` 在 NoneBot 启动时创建运行时，`probe` 还会执行最小可用性探测。 |
| admission gate | composition 级操作门禁；关闭开始后拒绝新操作，并等待已经获准的操作完成。 |

对象和关闭语义见 [Application API](application.md)与[启动与生命周期](../configuration/lifecycle.md)。

## 内容与资源

| 术语 | 定义 |
| --- | --- |
| Preparation | 将 HTML、Markdown、文本或 Jinja 模板转换为后端中立表示的阶段，不执行位图渲染。 |
| `PreparedHtml` | 由 `prepare_*` 工厂创建的中立文档；保留原始 HTML，并携带样式、资源、执行需求、文档基址与结构快照。 |
| `PreparedAsset` | 已读取并准备交给执行后端的资源内容及其媒体类型等元数据。 |
| Resource Service | 负责资源识别、访问授权、读取、缓存与 transport 物化的核心服务。 |
| `ResourcePolicy` | 单次操作的资源解析策略：`off` 跳过解析，`auto` 容忍无法解析的引用，`strict` 遇到任一失败即终止。 |
| `ResourceRef` | 尚未读取的资源引用；可以表示本地路径、包资源、远程 URL 或内联 bytes。 |

构造函数与资源辅助接口见 [Preparation 与资源 API](preparation.md)，部署和访问边界见[资源与访问策略](../configuration/resources.md)。

## 后端与扩展

| 术语 | 定义 |
| --- | --- |
| HTML 后端 | 消费 `PreparedHtml` 并执行 HTML 渲染的实现类别；通过 `render.provider` 一次选择 Playwright、HTMLKit 或 Takumi 中的一个。 |
| Provider | HTML 后端的扩展与 composition 契约；第一方和第三方实现均实现 `EngineProvider`。Pillow 与 Skia 不是 Provider。 |
| `EngineProvider` | Provider SDK 中负责 settings、availability、resource strategy、lifecycle、executor 与 Capability bindings 的公开协议。 |
| Graphics 后端 | 消费 `RasterScene` 的 Pillow 或 Skia adapter；通过 `render.graphics.backends` 独立启用。 |
| adapter | 位于系统边界的具体技术实现，把浏览器、native renderer、filesystem 或观测系统接入核心端口。 |
| Capability | 无法放入通用 `Renderer` 契约的专属操作，例如 Playwright Page、Takumi API 或指定 Graphics 后端。 |
| typed Capability | 第一方从 `app.extensions` 的静态属性发现，第三方由稳定 `CapabilityKey` 与 Protocol 标识；两者都不依赖字符串猜测或隐式回退。 |
| `RasterScene` | 后端中立的物理像素场景；当前由画布、背景、矩形命令与编码选项组成，不表达 HTML layout 或文本 shaping。 |

后端选择见[选择渲染后端](../start/choosing-provider.md)，扩展接口见[Capability 参考](capabilities.md)与 [Provider 契约](../extensions/provider-contract.md)。

## 请求与结果

| 术语 | 定义 |
| --- | --- |
| request | 交给 `Renderer` 或专属 Capability 的类型化操作输入，包含内容、选项、资源策略和超时等边界。 |
| artifact | 成功操作返回的类型化结果，保存 payload 及其格式、媒体类型或尺寸等元数据。 |
| `RenderedImage` | 编码后的图片 artifact；使用 `bytes(artifact)` 取得原始字节，并从对象读取实际格式、媒体类型和物理尺寸。 |
| `RenderedHtml` | HTML artifact；使用 `str(artifact)` 取得字符串内容。 |
| stable error | 在公共边界翻译后的 `RenderingError` 子类；提供有界摘要和原因快照，调用方不需要依赖具体浏览器或 native 库的内部异常。 |

完整函数、request、artifact 与错误契约见[渲染 API](rendering.md)。
