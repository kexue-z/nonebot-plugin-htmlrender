from pathlib import Path

from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import render_template, render_text

TEMPLATE_DIR = Path(__file__).parent / "templates"

profile = on_alconna(Alconna("profile", Args["username?", str]))


@profile.handle()
async def _(username: str = "NoneBot User") -> None:
    artifact = await render_template(
        TEMPLATE_DIR,
        template_name="profile.html",
        variables={
            "avatar_text": username[0].upper(),
            "username": username,
            "level": 42,
            "signature": "Talk is cheap, show me the code.",
            "stats": [
                {"label": "Days", "value": "128"},
                {"label": "Plugins", "value": "15"},
                {"label": "Messages", "value": "3.2k"},
            ],
        },
        width=440,
        height=None,
        device_pixel_ratio=1.0,
    )
    await profile.finish(UniMessage(Image(raw=bytes(artifact))))


text_render = on_alconna(Alconna("textimg", Args["content", str]))


@text_render.handle()
async def _(content: str) -> None:
    artifact = await render_text(content, width=600, device_pixel_ratio=1.0)
    await text_render.finish(UniMessage(Image(raw=bytes(artifact))))
