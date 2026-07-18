---
title: 示例项目
description: HTML Provider、typed Capability、RasterScene 与第三方 Provider 示例
icon: lucide/folder-code
---

# 示例项目

仓库中的示例都使用 0.8 公共边界，并由 Ruff、basedpyright、ty 与文档契约共同
检查。不同示例刻意覆盖不同的组合边界：

| 示例 | 边界 | 默认依赖 |
| --- | --- | --- |
| `template_render` | 引擎中立 HTML/文本 API | Playwright，可切换 Takumi/HTMLKit |
| `screenshot` | Playwright typed Capability | Playwright |
| `remote_browser` | Playwright CDP/WS transport | Playwright |
| `takumi_capability` | Takumi typed Capability 与 runtime lease | Takumi |
| `graphics_render` | 独立 Pillow/Skia `RasterScene` Capability | Pillow，可增加 Skia |
| `echo-provider` | 第三方 `EngineProvider` distribution | core SDK |

## 本地模板

`examples/template_render` 展示：

- `render_template(..., variables=...)`
- 中立的 `width` / `height` raster 参数
- `RenderedImage` 到消息 bytes 的显式转换
- 用三种静态 HTML Provider 都能表达的 `height=None` 与
  `device_pixel_ratio=1.0`

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

模板目录须列入 `render.resources.local_access.allowed_paths`；相对 stylesheet
与图片由 Preparation/Resource Service 处理。README 给出 Playwright、Takumi 与
HTMLKit 三套选择配置。HTMLKit 仍只支持其文档声明的静态 HTML/CSS 子集，不能据此
推导出浏览器等价性。

## 网页截图

`examples/screenshot` 从默认 `Application` 获取 Playwright Capability：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import PLAYWRIGHT_PAGE

playwright = get_default_application().extensions.require(PLAYWRIGHT_PAGE)
async with playwright.page(viewport={"width": 1280, "height": 800}) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    raw = await page.screenshot(full_page=True, type="png")
```

选择器截图使用 `playwright.capture_element(...)`。

## 远程浏览器

`examples/remote_browser` 展示 CDP/WS 连接、`Application.probe()` 和同一
Capability API。调用代码不因本地或远程连接而改变；资源 transport 在
Provider 配置中选择。

## Takumi 专属能力

`examples/takumi_capability` 展示稳定 lookup key 与 native extension lease：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import TAKUMI_CAPABILITIES

takumi = get_default_application().extensions.require(TAKUMI_CAPABILITIES)
async with takumi.extension() as extension:
    raw = await extension.render_html(
        "<strong>Takumi</strong>",
        width=640,
        height=240,
        device_pixel_ratio=1.0,
    )
```

`extension` 不能逃逸出异步上下文。普通 HTML、Markdown 与模板仍使用中立顶层 API；
只有 Takumi 的 node、measure、SVG、animation、动态字体或专属参数才进入此路径。

## Pillow/Skia RasterScene

`examples/graphics_render` 使用同一个物理像素级场景请求，但显式选择 backend key：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.graphics import (
    PILLOW_RASTER_SCENE_RENDERER,
    RasterScene,
    RenderRasterSceneRequest,
)

pillow = get_default_application().extensions.require(PILLOW_RASTER_SCENE_RENDERER)
image = await pillow.render(RenderRasterSceneRequest(RasterScene(640, 360)))
```

Pillow/Skia 不进入 `render.provider`。示例默认只安装兼容面更广的 Pillow；需要 Skia
时显式安装 extra，并在 `render.graphics.backends` 中启用。两个 backend 共享像素与
并发预算，但不承诺相同编码 bytes。

## 第三方 Provider

`examples/echo-provider` 是独立 distribution：

- 通过 `nonebot_plugin_htmlrender.providers` entry point 注册；
- 解析 `render.provider_config`；
- 返回 lifecycle 与 `PreparedHtmlExecutor` bindings；
- 只通过收窄的 `ProviderResources` 访问资源；
- 不读取 NoneBot 全局配置，不创建全局 observer。

它只返回固定颜色的 1×1 PNG，用于验证 discovery 与 SDK 接线，不是通用
图片 Provider。

## 可选观测

Sentry 与 Prometheus 是 composition 注入的横切 observer，不为每个引擎复制一套
示例。任意示例安装对应 extras 后，都可在同一个 `render` 配置中开启：

```bash
uv add "nonebot-plugin-htmlrender[playwright,sentry,prometheus]>=0.8.0a1,<0.9"
```

```yaml
render:
  provider: playwright
  observability:
    sentry: true
    prometheus: true
```

Provider、graphics 与专属 Capability 都会经过同一个 observer fan-out；exporter
失败不会替换渲染结果或原始业务异常。

## 运行

每个 NoneBot 示例均有独立 `pyproject.toml`，最低要求 NoneBot 2.5。复制对应 plugin
目录到项目后，安装 0.8 prerelease 与所需 Provider/Capability extra，再按 README
写入 `RENDER` 配置。
