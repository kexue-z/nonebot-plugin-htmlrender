from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import get_default_application

screenshot = on_alconna(Alconna("screenshot", Args["url?", str]))


@screenshot.handle()
async def _(url: str = "https://github.com") -> None:
    playwright = get_default_application().extensions.playwright
    async with playwright.page(
        viewport={"width": 1280, "height": 800},
    ) as page:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        img = await page.screenshot(full_page=True, type="png")

    await screenshot.finish(UniMessage(Image(raw=img)))


capture = on_alconna(Alconna("capture", Args["selector", str]))


@capture.handle()
async def _(selector: str = "div.application-main") -> None:
    playwright = get_default_application().extensions.playwright
    async with playwright.page(
        viewport={"width": 1280, "height": 800},
    ) as page:
        await page.goto("https://github.com", wait_until="networkidle", timeout=30000)
        img = await page.locator(selector).screenshot(type="png")

    await capture.finish(UniMessage(Image(raw=img)))
