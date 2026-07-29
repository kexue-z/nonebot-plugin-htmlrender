from nonebot import require

require("nonebot_plugin_htmlrender")

from arclet.alconna import Alconna, Args
from nonebot_plugin_alconna import Image, UniMessage, on_alconna

from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    PixelRect,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)

graphics_scene = on_alconna(Alconna("graphics_scene", Args["backend?", str]))


@graphics_scene.handle()
async def _(backend: str = "pillow") -> None:
    extensions = get_default_application().extensions
    if backend == "pillow":
        renderer = extensions.pillow
    elif backend == "skia":
        renderer = extensions.skia
    else:
        await graphics_scene.finish("backend must be pillow or skia")

    image = await renderer.render(
        RenderRasterSceneRequest(
            RasterScene(
                width=640,
                height=360,
                background=RGBAColor(15, 23, 42),
                commands=(
                    FillRect(
                        PixelRect(x=48, y=48, width=544, height=264),
                        RGBAColor(30, 41, 59),
                    ),
                    FillRect(
                        PixelRect(x=80, y=88, width=208, height=184),
                        RGBAColor(139, 92, 246),
                    ),
                    FillRect(
                        PixelRect(x=320, y=88, width=240, height=48),
                        RGBAColor(56, 189, 248),
                    ),
                    FillRect(
                        PixelRect(x=320, y=160, width=184, height=32),
                        RGBAColor(45, 212, 191, 192),
                    ),
                    FillRect(
                        PixelRect(x=320, y=216, width=120, height=32),
                        RGBAColor(251, 191, 36, 224),
                    ),
                ),
            )
        )
    )
    await graphics_scene.finish(UniMessage(Image(raw=bytes(image))))
