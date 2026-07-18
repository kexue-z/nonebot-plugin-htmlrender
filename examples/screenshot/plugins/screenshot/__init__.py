from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import PLAYWRIGHT_CAPABILITIES

screenshot = on_alconna(Alconna("screenshot", Args["url?", str]))


@screenshot.handle()
async def _(url: str = "https://github.com") -> None:
    playwright = get_default_application().capabilities.require(PLAYWRIGHT_CAPABILITIES)
    async with playwright.page(
        viewport={"width": 1280, "height": 800},
    ) as page:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        img = await page.screenshot(full_page=True, type="png")

    await screenshot.finish(UniMessage(Image(raw=img)))


capture = on_alconna(Alconna("capture", Args["selector", str]))


@capture.handle()
async def _(selector: str = "div.application-main") -> None:
    playwright = get_default_application().capabilities.require(PLAYWRIGHT_CAPABILITIES)
    img = await playwright.capture_element(
        "https://github.com",
        selector,
        page_kwargs={"viewport": {"width": 1280, "height": 800}},
        goto_kwargs={"wait_until": "networkidle", "timeout": 30000},
        screenshot_kwargs={"type": "png"},
    )
    await capture.finish(UniMessage(Image(raw=img)))
