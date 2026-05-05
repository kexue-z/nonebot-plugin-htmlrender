from typing import TYPE_CHECKING

from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import capture_html_element, get_render_context

if TYPE_CHECKING:
    from playwright.async_api import Page

screenshot = on_alconna(Alconna("screenshot", Args["url?", str]))


@screenshot.handle()
async def _(url: str = "https://github.com") -> None:
    async with get_render_context(
        viewport={"width": 1280, "height": 800},
    ) as context:
        page: Page = context  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        await page.goto(url, wait_until="networkidle", timeout=30000)
        img = await page.screenshot(full_page=True, type="png")

    await screenshot.finish(UniMessage(Image(raw=img)))


capture = on_alconna(Alconna("capture", Args["selector", str]))


@capture.handle()
async def _(selector: str = "div.application-main") -> None:
    img = await capture_html_element(
        "https://github.com",
        selector,
        page_kwargs={"viewport": {"width": 1280, "height": 800}},
        goto_kwargs={"wait_until": "networkidle", "timeout": 30000},
        screenshot_kwargs={"type": "png"},
    )
    await capture.finish(UniMessage(Image(raw=img)))
