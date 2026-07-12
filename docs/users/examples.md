---
title: 示例项目
description: typed artifact、模板与 Playwright Capability 示例
icon: lucide/folder-code
---

# 示例项目

仓库中的示例都使用 0.8 公共边界。

## 本地模板

`examples/template_render` 展示：

- `render_template(..., variables=...)`
- 中立的 `width` / `height` raster 参数
- `RenderedImage` 到消息 bytes 的显式转换

```python
artifact = await render_template(
    TEMPLATE_DIR,
    "profile.html",
    variables={"username": username},
    width=440,
    height=300,
)
await matcher.finish(UniMessage(Image(raw=bytes(artifact))))
```

模板目录须列入 `render.resources.local_access.allowed_paths`；相对 stylesheet
与图片由 Preparation/Resource Service 处理。

## 网页截图

`examples/screenshot` 从默认 `Application` 获取 Playwright Capability：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PLAYWRIGHT_CAPABILITIES,
)

playwright = get_default_application().capabilities.require(
    PLAYWRIGHT_CAPABILITIES
)
async with playwright.page(viewport={"width": 1280, "height": 800}) as page:
    await page.goto("https://example.com", wait_until="networkidle")
    raw = await page.screenshot(full_page=True, type="png")
```

选择器截图使用 `playwright.capture_element(...)`。

## 远程浏览器

`examples/remote_browser` 展示 CDP/WS 连接、`Application.probe()` 和同一
Capability API。调用代码不因本地或远程连接而改变；资源 transport 在
Provider 配置中选择。

## 第三方 Provider

`examples/echo-provider` 是独立 distribution：

- 通过 `nonebot_plugin_htmlrender.providers` entry point 注册；
- 解析 `render.provider_config`；
- 返回 lifecycle 与 `PreparedHtmlExecutor` bindings；
- 不读取 NoneBot 全局配置，不创建全局 observer。

它只返回固定颜色的 1×1 PNG，用于验证 discovery 与 SDK 接线，不是通用
图片 Provider。

## 运行

每个 NoneBot 示例均有独立 `pyproject.toml`。复制对应 plugin 目录到项目后，
安装 0.8 prerelease 与所需 Provider extra，再按 README 写入 `RENDER` 配置。
