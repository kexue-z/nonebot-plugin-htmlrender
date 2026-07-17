---
title: API
description: 0.8 通用渲染、Preparation、Capability 与错误模型
icon: lucide/code-xml
---

# API

## 通用渲染函数

所有函数返回类型化产物，只接受跨 Provider 可移植的参数。

| 函数 | 输入 | 返回 |
| --- | --- | --- |
| `render_html` | HTML、raster 选项、资源基址 | `RenderedImage` |
| `render_text` | 纯文本、可选 CSS、资源策略 | `RenderedImage` |
| `render_markdown` | Markdown 字符串或文件 | `RenderedImage` |
| `render_template` | Jinja 根目录、模板名、变量 | `RenderedImage` |
| `render_template_html` | Jinja 输入 | `RenderedHtml` |
| `rasterize_html` | `PreparedHtml`、`RasterOptions` | `RenderedImage` |

```python
from nonebot_plugin_htmlrender import (
    ResourcePolicy,
    render_html,
    render_template_html,
)

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

html = await render_template_html(
    "templates",
    "card.html",
    variables={"name": "Alice"},
)
source = str(html)
```

`quality` 只能与 JPEG 一起使用。`timeout_seconds` 覆盖完整操作；值必须为有限正数。

## Request 与 Renderer

需要复用请求或显式控制对象图时，直接构造 request：

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

只需要 facade 时可调用 `get_default_renderer()`；它等价于读取默认
`Application.renderer`，不会建立第二个 composition。

`Renderer.capabilities` 是已绑定通用用例的名称集合；
`Renderer.supports("render_html")` 可用于功能探测。

## 类型化产物

`RenderedImage` 提供：

- `data: bytes`
- `format: Literal["png", "jpeg"]`
- `width: int`
- `height: int`
- `media_type: str`
- `bytes(artifact)`

格式与尺寸来自后端实际返回的编码数据；尺寸是最终图片的物理像素，不是请求中的
CSS viewport。因而 DPR 与 Playwright full-page 截图也能得到准确元数据。
构造时只检查识别格式与尺寸所需的有界容器元数据，不替代图片解码器的完整校验。

`RenderedHtml` 提供 `content: str` 与 `str(artifact)`。不要依赖隐式类型转换。

## Preparation

Preparation 不执行位图渲染，可用来检查或复用中立文档：

```python
from nonebot_plugin_htmlrender import (
    RasterOptions,
    prepare_html,
    rasterize_html,
)

prepared = prepare_html(
    "<img src='avatar.png'>",
    base_url="https://static.example/assets/",
)
artifact = await rasterize_html(
    prepared,
    RasterOptions(width=480, device_pixel_ratio=2),
)
```

`prepare_text`、`prepare_markdown`、`prepare_template` 是异步函数；
`PreparedHtml` 由 HTML、stylesheets、assets、`base_url` 和 requirements 组成。
`prepare_markdown(markdown=..., resource_policy=...)` 与渲染 API 使用同一
`ResourcePolicy` 语义。

## 资源辅助函数

`resolve_template_vars` 递归解析映射和序列中的路径/bytes，
`to_resource_url` 处理单个值。两者均为异步函数，并使用组合出的资源策略。
`template_base` 只负责相对路径定位，不会扩张本地访问白名单。
`strict=None` 继承组合策略，`strict=False` 显式采用宽松解析，
`strict=True` 则在任一资源无法解析时失败。

```python
from nonebot_plugin_htmlrender import resolve_template_vars, to_resource_url

variables = await resolve_template_vars(
    {"avatar": "assets/avatar.png"},
    template_base="templates",
    strict=True,
)
logo_url = await to_resource_url(
    "assets/logo.svg",
    template_base="templates",
    strict=True,
)
```

## Application 生命周期

NoneBot bootstrap 负责默认 `Application` 的安装与关闭。手工组合或测试替身可使用：

```python
from nonebot_plugin_htmlrender import get_default_application

app = get_default_application()
await app.startup()
await app.probe()
await app.aclose()
```

`startup()` 与 `aclose()` 幂等。`aclose()` 会先拒绝新的 Renderer、Preparation 与
Resource Service 异步操作，等待已经获准的完整操作结束，再清理 Provider 与缓存；
即使调用方事先保留了这些 facade 的引用，关闭后也不能重新填充缓存。关闭失败可重试，
但一旦进入关闭流程便永久拒绝新操作；需要再次渲染时应创建新的 composition。

## RasterScene Capability

Pillow 与 Skia 接受同一个后端中立、物理像素级 `RasterScene`，但分别注册为独立
typed Capability。调用方必须明确要求需要的后端：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.graphics import (
    PILLOW_RASTER_SCENE_RENDERER,
    SKIA_RASTER_SCENE_RENDERER,
    FillRect,
    PixelRect,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)

app = get_default_application()
pillow = app.capabilities.require(PILLOW_RASTER_SCENE_RENDERER)
skia = app.capabilities.require(SKIA_RASTER_SCENE_RENDERER)

request = RenderRasterSceneRequest(
    scene=RasterScene(
        width=320,
        height=180,
        background=RGBAColor(255, 255, 255),
        commands=(
            FillRect(
                PixelRect(x=24, y=24, width=128, height=72),
                RGBAColor(229, 57, 53, 192),
            ),
        ),
    ),
    output=RasterEncodeOptions(format="png"),
)
image = await pillow.render(request)
```

`PixelRect` 使用整数、左闭右开的坐标，超出画布的部分会被裁剪；命令按 tuple 顺序
使用 source-over 合成。JPEG 可通过 `RasterEncodeOptions` 指定 `quality` 和不透明
`matte`。两个后端不会泄露 Pillow/Skia 原生对象，也不承诺产生相同 bytes 或精确
channel 值。

这两项能力不是 `EngineProvider`，不进入 `render.provider`、HTMLKit/Playwright/Takumi
Provider discovery 或通用 HTML request。它们由 `render.graphics.backends` 显式
启用；缺失配置的 key 会抛出 `CapabilityUnavailable`，缺少已配置 backend 的 extra
会在 composition 时抛出 `RasterBackendUnavailable`。安装、平台限制与共享资源预算
见 [Pillow 与 Skia 位图场景](config/graphics.md)。

## Playwright Capability

页面导航、header、User-Agent、选择器截图属于浏览器专属语义：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PLAYWRIGHT_CAPABILITIES,
)

playwright = get_default_application().capabilities.require(PLAYWRIGHT_CAPABILITIES)
async with playwright.page(
    viewport={"width": 1280, "height": 800},
    locale="zh-CN",
) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    image = await page.screenshot(full_page=True, type="png")

element = await playwright.capture_element(
    "https://example.com",
    "main",
    page_kwargs={"viewport": {"width": 1280, "height": 800}},
)
```

缺少 Playwright Provider 时 `require()` 抛出 `CapabilityUnavailable`。

## Takumi Capability

Takumi 的 node、measure、SVG、animation 与动态字体 API 通过专属 Capability 获取：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.adapters.takumi.capabilities import (
    TAKUMI_CAPABILITIES,
)

takumi = get_default_application().capabilities.require(TAKUMI_CAPABILITIES)
async with takumi.extension() as extension:
    svg = await extension.render_svg_html("<strong>Hello</strong>", width=320)
```

`extension()` 的异步上下文持有一次 operation lease；不要让 `extension` 对象
逃逸出上下文。

## 稳定错误模型

通用 request 的参数校验、Preparation、Resource Service、Application 生命周期与
executor 边界由库产生或翻译的错误都继承 `RenderingError`：

| 错误 | 含义 |
| --- | --- |
| `InvalidRenderRequest` | request 在执行前已确定无效 |
| `PreparationError` | 模板编译或其他中立内容准备失败 |
| `ProviderNotConfigured` | 默认 Application 尚未由插件或调用方安装 |
| `ProviderNotFound` | 配置的 Provider ID 无法发现 |
| `ProviderUnavailable` | Provider 存在但当前环境不可运行 |
| `CapabilityUnavailable` | composition 未绑定请求的操作或 typed Capability；`provider: null` 的位图调用也属于此类 |
| `UnsupportedRenderOption` | 选定 Provider 无法准确表示某个通用 raster 选项 |
| `UnsupportedRequirement` | 文档需求超出 Provider 能力 |
| `ResourceResolutionError` | 资源读取、授权或物化失败 |
| `ProviderExecutionError` | Provider 执行失败 |
| `ProviderLifecycleError` | startup、probe 或关闭失败 |
| `RasterBackendUnavailable` | 已配置 Pillow/Skia backend，但依赖或运行环境不可用 |
| `RasterBackendExecutionError` | Pillow/Skia native draw 或 encode 失败 |

通用 executor 与 graphics adapter 的边界会把 native 异常翻译为这些类型；业务
代码不应捕获引擎内部异常作为稳定契约。typed Capability 可以属于 Provider，也可
像 Pillow/Skia 一样独立组合。获取缺失 Capability 与 lease 生命周期仍使用上述稳定
错误；但 raw Playwright `Page` 或 Takumi extension 内的专属操作可能直接抛出对应
引擎异常，调用方需按该 Capability 文档处理。
