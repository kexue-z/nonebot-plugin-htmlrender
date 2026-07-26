from html import escape

from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import get_default_application

CARD_STYLE = """
body {
    margin: 0;
    background: #111827;
    color: #f9fafb;
    font-family: sans-serif;
}
.card {
    margin: 24px;
    padding: 28px;
    border-radius: 18px;
    background: #1f2937;
    border: 2px solid #8b5cf6;
}
.title {
    font-size: 32px;
    font-weight: 700;
}
.subtitle {
    margin-top: 12px;
    color: #c4b5fd;
    font-size: 18px;
}
"""

takumi_card = on_alconna(Alconna("takumi_card", Args["title?", str]))


@takumi_card.handle()
async def _(title: str = "Takumi Capability") -> None:
    takumi = get_default_application().extensions.takumi
    html = (
        '<div class="card">'
        f'<div class="title">{escape(title)}</div>'
        '<div class="subtitle">Rendered through a leased native extension</div>'
        "</div>"
    )

    async with takumi.api() as api:
        image = await api.render_html(
            html,
            stylesheets=(CARD_STYLE,),
            width=640,
            height=240,
            device_pixel_ratio=1.0,
        )

    await takumi_card.finish(UniMessage(Image(raw=image)))
