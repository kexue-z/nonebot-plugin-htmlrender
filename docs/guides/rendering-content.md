---
title: 渲染内容
description: 使用通用 API 渲染 HTML、Markdown、文本和 Jinja 模板
icon: lucide/file-image
---

# 渲染内容

内容到图片优先使用通用 `render_*` API。只有导航、selector、node、SVG 等无法跨Provider 表达的操作才获取 typed Capability。

## HTML、Markdown 与文本

```python
from nonebot_plugin_htmlrender import render_html, render_markdown, render_text

html_image = await render_html("<main>Hello</main>", width=800)
markdown_image = await render_markdown("# Hello", width=800)
text_image = await render_text("Hello", width=800)
```

函数返回 `RenderedImage`。需要交给消息、HTTP 或文件 API 时调用`bytes(image)`；使用 `image.media_type`、`width` 和 `height` 读取实际编码元数据。

!!! warning "Markdown 中的原始 HTML 会进入页面"

    `render_markdown` 保留原始 HTML，并不负责消毒不可信内容。用户或模型输入应先按业务策略清洗标签、属性和 URL；不需要富文本时使用 `render_text`。完整威胁边界见[安全须知](../configuration/security.md#untrusted-html-and-templates)。

## Jinja 模板

`examples/template_render` 展示引擎中立的模板渲染：

```python
artifact = await render_template(
    TEMPLATE_DIR,
    "profile.html",
    variables={"username": username},
    width=440,
    height=None,
    device_pixel_ratio=1.0,
)
await matcher.finish(UniMessage(Image(raw=bytes(artifact))))
```

模板目录须列入 `render.resources.local_access.allowed_paths`；相对 stylesheet 与图片由 Preparation 和 Resource Service 处理。具体组织方式见[模板与资源](templates-and-resources.md)。

## 选择专属路径

- 网页导航、selector 或 raw Page：使用 [Playwright 页面指南](browser-automation.md)。
- Takumi node、measure、SVG、animation 或动态字体：使用 `app.extensions.takumi.api()`。
- 无 HTML 的物理像素绘制：使用 [RasterScene](raster-scenes.md)。
- 第三方 Provider distribution：从[Provider 开发指南](../extensions/provider-development.md)开始。

仓库中的 `examples/screenshot`、`examples/remote_browser`、`examples/takumi_capability` 与 `examples/graphics_render` 分别展示这些组合方式。完整函数、request 与返回类型见[渲染 API](../reference/rendering.md)。
