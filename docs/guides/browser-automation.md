---
title: 操作浏览器页面
description: 通过 Playwright Capability 执行导航、页面操作与元素截图
icon: lucide/mouse-pointer-click
---

# 操作浏览器页面

页面导航、header、User-Agent、selector 和 raw `Page` 属于 Playwright 专属语义，通过 `app.extensions.playwright` 获取。

```python
from nonebot_plugin_htmlrender import get_default_application

playwright = get_default_application().extensions.playwright
async with playwright.page(
    viewport={"width": 1280, "height": 800},
    locale="zh-CN",
) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    image = await page.screenshot(full_page=True, type="png")
```

`Page` 的有效期仅限于当前 `async with playwright.page()` 上下文；离开上下文后不得保存或继续使用。上下文内直接调用 Playwright API 时保留 Playwright 原生异常；只有通用 Renderer、Provider、资源处理和生命周期边界才会将对应失败翻译为稳定的htmlrender 错误。

元素截图直接组合 Playwright 原生的 `Page.goto()`、`Page.locator()` 与`Locator.screenshot()`；三段调用的参数和返回值均由当前 Playwright 版本提供类型：

```python
async with playwright.page(viewport={"width": 1280, "height": 800}) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    element = await page.locator("main").screenshot(type="png")
```

`page()` 的参数列表同样从 `Browser.new_page()` 的类型签名投影而来，不在htmlrender 内维护第二份 kwargs 模型。升级 Playwright 后，IDE 会直接显示对应版本新增或调整的页面参数。

本地、WS 与 CDP 使用同一调用方式；连接和资源 transport 见[远程 Playwright 部署](../configuration/remote-playwright.md)，完整接口见[Capability 参考](../reference/capabilities.md)。

## 直接使用 Browser

需要多个 `BrowserContext`、tracing、CDP session 或 Playwright 后续版本新增能力时，通过 `playwright.browser()` 获取 Provider 持有的原生 `Browser`。该入口不重新描述任何 Browser 方法，也不使用 proxy；上下文仅持有 execution lease 并记录`playwright.native.browser` telemetry。

调用方必须在上下文内关闭自己创建的 context/page/session，且不得调用`browser.close()`。对象逃逸或关闭共享 Browser 可能影响并发渲染；这是高级原生入口明确接受的风险，详见 [Capability 参考](../reference/capabilities.md#playwright)。
