---
title: Capability 参考
description: RasterScene、Playwright 与 Takumi 的类型化扩展接口
icon: lucide/plug-zap
---

# Capability 参考

Capability 承载无法跨 Provider 统一表达的操作。第一方能力通过`app.extensions` 的静态属性直接发现；`CapabilityKey` 与 `require()` 仅用于第三方自定义扩展。Provider 组合阶段仍使用公共 `CapabilityCatalog` 注册和合并 bindings，但业务代码不需要绕过 `ApplicationExtensions` 直接读取它。`adapters.*.capabilities` 是实现细节。

## RasterScene

Pillow 与 Skia 接受同一个后端中立、物理像素级 `RasterScene`，分别通过`app.extensions.pillow` 与 `.skia` 获取。它们不进入 `render.provider`和通用 HTML request。

`PixelRect` 使用整数、左闭右开坐标，超出画布的部分会裁剪；命令按 tuple 顺序使用source-over 合成。JPEG 可指定 `quality` 与不透明 `matte`。缺少已配置 backend 的extra 会在 composition 时抛出 `RasterBackendUnavailable`，native draw 或 encode失败翻译为 `RasterBackendExecutionError`。

完整调用示例见[绘制 RasterScene](../guides/raster-scenes.md)。

## Playwright

```python
from nonebot_plugin_htmlrender import get_default_application

playwright = get_default_application().extensions.playwright
async with playwright.page(viewport={"width": 1280, "height": 800}) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    image = await page.screenshot(full_page=True, type="png")
```

页面导航、header、User-Agent 和 selector 截图属于浏览器语义。缺少 Playwright
Provider 时属性访问抛出 `CapabilityUnavailable`。`Page` 的有效期仅限于当前`async with playwright.page()` 上下文；离开后不得保存或继续使用。上下文内的 raw
Page 操作保留 Playwright 原生异常。

需要 `Browser.new_context()`、context tracing、CDP session 等完整 Playwright 能力时，从同一个 Playwright access 获取 Provider 实际持有的 `Browser`：

```python
playwright = get_default_application().extensions.playwright
async with playwright.browser() as browser:
    context = await browser.new_context(locale="zh-CN")
    try:
        page = await context.new_page()
        await page.goto("https://example.com")
    finally:
        await context.close()
```

`browser` 没有 proxy，类型、对象身份和全部方法均来自当前 Playwright。该 Browser由 Provider 所有，调用方不得关闭它；调用方创建的 `BrowserContext`、`Page`、tracing与 CDP session 则由调用方在退出上下文前关闭。`Browser` 同样不得逃逸`browser()` 上下文；上下文只约束租约生命周期，不代理原生操作或翻译 Playwright异常。

## Takumi

```python
from nonebot_plugin_htmlrender import get_default_application

takumi = get_default_application().extensions.takumi
async with takumi.api() as api:
    svg = await api.render_svg_html("<strong>Hello</strong>", width=320)
```

`api` 的有效期仅限于当前 `async with takumi.api()` 上下文；该上下文持有对应的runtime lease。`TakumiCompiledDocument`、compiled node/stylesheet 以及原生 Renderer同样绑定当前 runtime，不得跨上下文保存或交给另一套 composition。渲染得到的`bytes`、SVG `str`、`MeasuredNode` 与 cache/font 快照是操作结果，可以在上下文结束后继续使用。

### 原生能力矩阵

矩阵中的方法均属于 `TakumiAPI`，由 `api()` 返回的 adapter完整实现。HTML 变体接受字符串或 `PreparedHtml`；compiled 变体复用`TakumiCompiledDocument`；node 与 animation 变体直接使用 `takumi-py` 的 typed输入。

| 类别 | 方法 | 结果与约束 |
| --- | --- | --- |
| <!-- takumi:compile --> Compile | `compile_html`、`compile_node`、`compile_stylesheet`、`compile_keyframes` | 返回绑定当前 runtime 的 compiled node、stylesheet 或 document |
| <!-- takumi:raster --> Raster | `render_html`、`render_compiled`、`render_node` | 返回原生编码的 `bytes`；CSS 尺寸按 `device_pixel_ratio` 映射到物理像素 |
| <!-- takumi:measure --> Measure | `measure_html`、`measure_compiled`、`measure_node` | 返回 `takumi_py.MeasuredNode`，不执行图片编码 |
| <!-- takumi:svg --> SVG | `render_svg_html`、`render_svg_compiled`、`render_svg_node` | 返回 SVG `str`；尺寸保持 CSS 像素语义 |
| <!-- takumi:animation --> Animation | `render_animation`、`render_sequence_at_time`、`encode_frames` | 返回 WebP/APNG/GIF 或单帧静态图片的 `bytes` |
| <!-- takumi:font --> Font | `register_font`、`register_fonts`、`register_font_file` | 在当前 runtime 注册字体并返回新增字体族 |

`registered_font_families` 与 `compiled_cache_stats` 是只读 runtime 快照。所有异步方法都有 `takumi.api.*` 形式的稳定 telemetry operation 名称；`render_sequence_at_time` 使用 `takumi.api.render_sequence`。这里是 Takumi 专属能力，不经过 neutral HTML executor，也不受 `render.html` 预算约束。统计字段的读取示例和 compiled cache 清理边界见[缓存组件、失效与调优](../guides/cache-lifecycle.md#takumi-compiled-font-and-image-caches)。

### 原生 Renderer { #native-renderer }

当 `TakumiAPI` 尚未覆盖上游新方法或动态渲染组合时，可以取得当前runtime 实际持有的 `takumi_py.Renderer`：

```python
from functools import partial

from anyio.to_thread import run_sync
from nonebot_plugin_htmlrender import get_default_application

takumi = get_default_application().extensions.takumi
async with takumi.renderer() as renderer:
    image = await run_sync(
        partial(
            renderer.render_node,
            {"type": "container"},
            width=640,
            height=360,
        )
    )
```

这里同样不使用 proxy，IDE 直接读取 `takumi-py` 的 Renderer 类型。Renderer 的方法是同步 native 调用；异步应用应自行切换 worker，并承担并发限制、panic、参数验证、资源归一化及原生异常等风险。不得保存或关闭 Provider 所有的 Renderer。

`playwright.native.page`、`playwright.native.browser` 与`takumi.native.renderer` 会记录整个原生访问上下文的耗时和成功/异常，并携带`render.access=native`。为了保持原生对象身份与完整类型，htmlrender 不代理上下文中的每个上游方法；调用方在内部捕获并吞掉的异常不会被自动记录为失败。

`takumi.api()` 为每个受管理方法提供 `takumi.api.*` telemetry，并把 native 失败收束为携带有界原因快照的 htmlrender 错误。`playwright.page()` 仍然返回原生`Page`：上下文本身有稳定 operation，但 `goto()`、`locator()`、`screenshot()` 等调用继续使用 Playwright 自身的异常。需要跨 Provider 的稳定错误时使用通用`render_*` / `Renderer` 边界。
