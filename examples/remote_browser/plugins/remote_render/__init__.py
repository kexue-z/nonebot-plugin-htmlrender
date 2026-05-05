from nonebot import require

require("nonebot_plugin_htmlrender")

from typing import TYPE_CHECKING

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

if TYPE_CHECKING:
    from playwright.async_api import Page

from nonebot_plugin_htmlrender import (
    get_render_context,
    list_render_backend_statuses,
    render_markdown,
)

status = on_alconna(Alconna("render_status"))


@status.handle()
async def _() -> None:
    statuses = list_render_backend_statuses()
    text = "\n".join(str(s) for s in statuses)
    await status.finish(text or "No backends registered.")


remote_screenshot = on_alconna(Alconna("rshot", Args["url?", str]))


@remote_screenshot.handle()
async def _(url: str = "https://github.com") -> None:
    async with get_render_context(
        viewport={"width": 1280, "height": 800},
    ) as context:
        page: Page = context  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        await page.goto(url, wait_until="networkidle", timeout=30000)
        img = await page.screenshot(full_page=True, type="png")

    await remote_screenshot.finish(UniMessage(Image(raw=img)))


remote_md = on_alconna(Alconna("rmd", Args["text", str]))


@remote_md.handle()
async def _(text: str) -> None:
    img = await render_markdown(text, width=720)
    await remote_md.finish(UniMessage(Image(raw=img)))
