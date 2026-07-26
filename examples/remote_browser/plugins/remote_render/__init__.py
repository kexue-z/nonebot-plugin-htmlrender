from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import (
    get_default_application,
    render_markdown,
)

status = on_alconna(Alconna("render_status"))


@status.handle()
async def _() -> None:
    app = get_default_application()
    await app.probe()
    names = ", ".join(sorted(app.extensions.names())) or "none"
    await status.finish(f"Provider is ready. Capabilities: {names}")


remote_screenshot = on_alconna(Alconna("rshot", Args["url?", str]))


@remote_screenshot.handle()
async def _(url: str = "https://github.com") -> None:
    playwright = get_default_application().extensions.playwright
    async with playwright.page(
        viewport={"width": 1280, "height": 800},
    ) as page:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        img = await page.screenshot(full_page=True, type="png")

    await remote_screenshot.finish(UniMessage(Image(raw=img)))


remote_md = on_alconna(Alconna("rmd", Args["text", str]))


@remote_md.handle()
async def _(text: str) -> None:
    artifact = await render_markdown(text, width=720)
    await remote_md.finish(UniMessage(Image(raw=bytes(artifact))))
