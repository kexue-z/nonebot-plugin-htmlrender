---
title: 渲染 API
description: 通用渲染函数、request、类型化产物与执行错误
icon: lucide/code-xml
---

# 渲染 API

## 通用渲染函数

所有函数返回类型化产物，只接受跨 Provider 可移植的参数。

| 函数 | 对应 request | 返回 |
| --- | --- | --- |
| `render_html` | `RenderHtmlRequest` | `RenderedImage` |
| `render_text` | `RenderTextRequest` | `RenderedImage` |
| `render_markdown` | `RenderMarkdownRequest` | `RenderedImage` |
| `render_template` | `RenderTemplateRequest` | `RenderedImage` |
| `render_template_html` | `RenderTemplateHtmlRequest` | `RenderedHtml` |
| `rasterize_html` | `RasterizeHtmlRequest` | `RenderedImage` |

```python
from nonebot_plugin_htmlrender import ResourcePolicy, render_html

image = await render_html(
    "<main>Hello</main>",
    width=800,
    height=480,
    device_pixel_ratio=2,
    image_format="png",
    resource_policy=ResourcePolicy.STRICT,
    timeout_seconds=15,
)
payload = bytes(image)
content_type = image.media_type
```

`RasterOptions.format` 与 `RenderedImage.format` 使用公共 `RasterImageFormat`（`"png" | "jpeg"`）。`quality` 只能与 JPEG 一起使用。`timeout_seconds` 必须是有限正数，并覆盖完整操作。

## Request 与 Renderer

```python
from nonebot_plugin_htmlrender import (
    RasterOptions,
    RenderHtmlRequest,
    get_default_application,
)

request = RenderHtmlRequest(
    html="<h1>Hello</h1>",
    raster=RasterOptions(width=640, format="png"),
    timeout_seconds=10,
)
artifact = await get_default_application().renderer.render_html(request)
```

`Renderer.supported_commands` 是已绑定通用用例的名称集合；`Renderer.supports("render_html")` 可用于功能探测。只需要 facade 时可调用`get_default_renderer()`，它不会建立第二个 composition。

## 类型化产物

`RenderedImage` 提供 `data`、`format`、`width`、`height`、`media_type` 和`bytes(artifact)`。格式与尺寸来自后端实际编码数据；尺寸是最终图片的物理像素，不是请求中的 CSS viewport。`RenderedHtml` 提供 `content` 与 `str(artifact)`。

## 稳定执行错误

| 错误 | 含义 |
| --- | --- |
| `InvalidRenderRequest` | request 在执行前已确定无效 |
| `PreparationError` | 模板编译或中立内容准备失败 |
| `CapabilityUnavailable` | composition 未绑定请求的通用或专属能力 |
| `UnsupportedRenderOption` | Provider 无法准确表示通用 raster 选项 |
| `UnsupportedRequirement` | 文档需求超出 Provider 能力 |
| `ResourceResolutionError` | 资源读取、授权或物化失败 |
| `ProviderExecutionError` | Provider 执行失败 |
| `RasterBackendExecutionError` | Graphics backend draw 或 encode 失败 |

这些错误都继承 `RenderingError`。native 异常在通用 Renderer/Provider、资源、生命周期、受管理的 Takumi API 和 Graphics adapter 边界收束；raw Playwright
`Page`/`Browser` 或 `takumi.renderer()` 内的调用仍保留对应引擎异常。

稳定错误不会把 native 异常对象或未经限制的 `str(error)` 保存为公共状态。每个`RenderingError` 提供以下可补全字段：

- `message: str`：归一化并限制长度的稳定摘要；
- `message_truncated: bool`：摘要是否发生裁剪；
- `causes: tuple[ErrorCause, ...]`：底层异常链及 `ExceptionGroup` 摘要与叶子的有限快照，每项包含 `exception_type`、`message` 与 `truncated`；
- `causes_truncated: bool`：是否还有未收入快照的底层异常。

```python
from nonebot.log import logger

from nonebot_plugin_htmlrender import RenderingError, render_html

try:
    image = await render_html("<main>Hello</main>")
except RenderingError as error:
    logger.warning("{}: {}", type(error).__name__, error.message)
    for cause in error.causes:
        logger.debug("{}: {}", cause.exception_type, cause.message)
```

`str(error)` 适合面向人的日志，内容为稳定摘要及有限的 `Caused by ...` 信息；程序分支应读取上述字段，而不是解析该字符串。原始异常仍通过 Python 的 `__cause__` 链交给日志和错误追踪系统。原因快照只做 ANSI/空白归一化与长度、数量限制，不负责业务数据脱敏；输出给用户或外部日志前仍应按应用策略过滤。
