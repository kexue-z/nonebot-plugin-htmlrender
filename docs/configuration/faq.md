---
title: 常见问题
description: 0.8 Provider、typed artifact 与资源模型常见问题
icon: lucide/circle-help
---

# 常见问题

## 为什么结果不能直接传给只接受 bytes 的 API？

`render_*` 返回 `RenderedImage`，它同时保存 format、MIME 类型和尺寸。请在I/O 边界使用 `bytes(artifact)` 或 `artifact.data`。

## 为什么配置了插件却不能渲染位图？

确认 `render.provider` 已选择、对应 extra 已安装，并检查`render.provider_config`。不选择 Provider 时，Preparation 和模板到 HTML仍可工作，但没有位图执行器。

## `startup: off` 是否表示禁用渲染？

不是。它表示延迟创建 Provider runtime。第一次需要执行器或 Capability 的操作会启动；希望启动失败尽早暴露时使用 `warmup` 或 `probe`。

## 如何操作 Playwright Page？

从 `get_default_application().extensions.playwright` 获取 typed access，再使用`page()` 上下文。通用 `render_*` 不接受浏览器专属参数。

## 如何判断当前 composition 是否提供某项能力？

通用渲染使用 `app.renderer.supports("render_html")`；第一方专属能力从`app.extensions.playwright`、`.takumi`、`.pillow` 或 `.skia` 直接发现。第三方自定义能力使用 `app.extensions.get(KEY)` 或 `require(KEY)`；后者缺失时抛出`CapabilityUnavailable`。

## `base_url` 会让浏览器导航吗？

不会。通用 `render_html(..., base_url=...)` 与 `PreparedHtml.base_url` 只用于相对资源解析。网页导航属于 Playwright Page：显式调用 `page.goto()`。

## 远程浏览器为什么看不到本地图片？

远端进程不能直接读取 Bot 的路径。保持`render.provider_config.remote_local_resource_policy: memory`，或在明确共享卷时使用 `passthrough`；确需 HTTP URL 时选择 `filehost` policy 并配置`render.resources.filehost.public_base_url`（资源由 htmlrender 自有的hosted asset store 提供服务）。

## 模板变量中的 Path/bytes 怎么处理？

`render_template` 的 Preparation 会处理资源值；独立处理可调用`resolve_template_vars` 或 `to_resource_url`。严格任务使用 `strict=True`。

## Playwright、HTMLKit 与 Takumi 怎么选？

需要 JavaScript、页面导航或完整浏览器 CSS 语义时选 Playwright；希望用轻量litehtml/Cairo 处理受控静态 HTML 时可评估实验性 HTMLKit；需要 Takumi 专属的native SVG/measure/animation 时选 Takumi。HTMLKit rc5 不支持通用 request 的精确DPR 或固定高度，不能作为 Playwright 的透明替代。

## 可以同时配置两个 Provider 吗？

默认 NoneBot composition 选择一个 `render.provider`。高级场景可在应用层创建多个独立 composition，但它们必须分别管理生命周期、缓存和 Capability。

## 如何从 0.7 升级？

阅读 [v0.8 迁移指南](../guides/migration/v0.8.md)。插件会拒绝旧配置键，不会静默猜测其含义。
