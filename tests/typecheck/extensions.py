"""Static probes for the public first-party extension completion chain."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing_extensions import assert_type

from playwright.async_api import Browser, Page, Response
from takumi_py import Renderer as TakumiRenderer

from nonebot_plugin_htmlrender.capabilities import (
    PlaywrightAccess,
    TakumiAccess,
    TakumiAPI,
)
from nonebot_plugin_htmlrender.graphics import RasterSceneRenderer

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.application import Application


async def _probe(app: Application) -> None:
    playwright = assert_type(app.extensions.playwright, PlaywrightAccess)
    async with playwright.page(viewport={"width": 800, "height": 600}) as page:
        assert_type(page, Page)
        assert_type(await page.goto("https://example.com"), Response | None)
        assert_type(await page.locator("main").screenshot(type="png"), bytes)

    async with playwright.browser() as browser:
        assert_type(browser, Browser)
        await browser.new_context(locale="zh-CN")

    takumi = assert_type(app.extensions.takumi, TakumiAccess)
    async with takumi.api() as api:
        assert_type(api, TakumiAPI)
        assert_type(await api.render_html("<strong>Hello</strong>"), bytes)

    async with takumi.renderer() as renderer:
        assert_type(renderer, TakumiRenderer)
        renderer.render_node({"type": "container"}, width=320, height=180)

    assert_type(app.extensions.pillow, RasterSceneRenderer)
    assert_type(app.extensions.skia, RasterSceneRenderer)
