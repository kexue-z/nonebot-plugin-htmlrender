---
title: HTML 渲染预算
description: 跨 Provider 统一实施的输入、输出与并发限制
icon: lucide/gauge
---

# HTML 渲染预算

`render.html` 由 composition 统一实施，适用于 `render_html`、`render_text`、`render_markdown`、`render_template` 与 `rasterize_html`。限制位于 Provider
executor 外层，因此切换 Playwright、HTMLKit 或 Takumi 不会改变拒绝语义。

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.html.max_source_bytes` | `67108864` | 单次 `PreparedHtml` 的 HTML、stylesheet 与 asset 总字节上限 |
| `render.html.max_pixels` | `16777216` | 编码结果的物理像素上限；显式高度请求也会在进入 Provider 前校验 |
| `render.html.max_output_bytes` | `67108864` | 编码图片的字节上限 |
| `render.html.max_device_pixel_ratio` | `4.0` | 允许的最大设备像素比 |
| `render.html.max_auto_height` | `16384` | `height=None` 时允许的最大内容驱动 CSS 高度 |
| `render.html.max_concurrency` | `2` | 当前 composition 内所有 HTML Provider executor 共享的并发槽 |

输入大小、设备像素比和显式宽高的物理像素数会在取得并发槽及调用 Provider之前校验。内容驱动高度只有 Provider 完成布局后才能确定，因此其高度、总物理像素与编码字节数作为统一的输出后置条件校验；并发限制仍会约束这类请求同时占用的运行时资源。

Provider 专属 capability 不经过 neutral HTML executor，仍由各 capability 自己的契约与 Provider 配置约束。
