import io
from nonebot_plugin_htmlrender import (
    text_to_pic,
    md_to_pic,
    template_to_pic,
    get_new_page,
)
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from PIL import Image

# 纯文本转图片
text2pic = on_command("text2pic")


@text2pic.handle()
async def _text2pic(bot: Bot, event: MessageEvent):
    msg = str(event.get_message())

    # css_path 可选
    # from pathlib import Path
    # pic = await text_to_pic(
    #     text=msg, css_path=str(Path(__file__).parent / "templates" / "markdown.css")
    # )

    pic = await text_to_pic(text=msg)
    a = Image.open(io.BytesIO(pic))
    a.save("text2pic.png", format="PNG")
    await text2pic.finish(MessageSegment.image(pic))


# 加载本地 html 方法
html2pic = on_command("html2pic")


@html2pic.handle()
async def _html2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    # html 可使用本地资源
    async with get_new_page(viewport={"width": 300, "height": 300}) as page:
        await page.goto(
            "file://" + (str(Path(__file__).parent / "html2pic.html")),
            wait_until="networkidle",
        )
        pic = await page.screenshot(full_page=True, path="./html2pic.png")

    await html2pic.finish(MessageSegment.image(pic))


# 使用 template2pic 加载模板
template2pic = on_command("template2pic")


@template2pic.handle()
async def _template2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    text_list = ["1", "2", "3", "4"]
    template_path = str(Path(__file__).parent / "templates")
    template_name = "text.html"
    # 设置模板
    # 模板中本地资源地址需要相对于 base_url 或使用绝对路径
    pic = await template_to_pic(
        template_path=template_path,
        template_name=template_name,
        templates={"text_list": text_list},
        pages={
            "viewport": {"width": 600, "height": 300},
            "base_url": f"file://{template_path}",
        },
        wait=2,
    )

    a = Image.open(io.BytesIO(pic))
    a.save("template2pic.png", format="PNG")

    await template2pic.finish(MessageSegment.image(pic))


# 使用 md2pic
md2pic = on_command("md2pic")


@md2pic.handle()
async def _md2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    # 如果是直接获取消息内容 需要 unescape
    from nonebot.adapters.onebot.v11 import unescape

    msg = unescape(str(event.get_message()))

    # css_path 可选
    # pic = await md_to_pic(
    #     md=msg, css_path=str(Path(__file__).parent / "templates" / "markdown.css")
    # )

    pic = await md_to_pic(md=msg)

    a = Image.open(io.BytesIO(pic))
    a.save("md2pic.png", format="PNG")

    await md2pic.finish(MessageSegment.image(pic))
