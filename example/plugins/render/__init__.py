import io

from nonebot import on_command
from nonebot.adapters.cqhttp import Bot, MessageEvent, MessageSegment
from nonebot.plugin import require
from PIL import Image

# 纯文本转图片
text2pic = on_command("text2pic")
text_to_pic = require("nonebot_plugin_htmlrender").text_to_pic


@text2pic.handle()
async def _text2pic(bot: Bot, event: MessageEvent):
    msg = str(event.get_message())

    
    from pathlib import Path
    
    # css_path 可选
    # pic = await text_to_pic(
    #     text=msg, css_path=str(Path(__file__).parent / "templates" / "markdown.css")
    # )

    pic = await text_to_pic(text=msg)
    a = Image.open(io.BytesIO(pic))
    a.save("text2pic.png", format="PNG")
    await text2pic.finish(MessageSegment.image(pic))


# 加载本地 html 方法
html2pic = on_command("html2pic")
new_page = require("nonebot_plugin_htmlrender").get_new_page


@html2pic.handle()
async def _html2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    # html 中需要包括样式表
    async with new_page(viewport={"width": 300, "height": 300}) as page:
        await page.goto(
            "file://" + (str(Path(__file__).parent / "html2pic.html")),
            wait_until="networkidle",
        )
        pic = await page.screenshot(full_page=True, path="./html2pic.png")

    await html2pic.finish(MessageSegment.image(pic))


# 使用 template2pic 加载模板
template2pic = on_command("template2pic")
template_to_html = require("nonebot_plugin_htmlrender").template_to_html
html_to_pic = require("nonebot_plugin_htmlrender").html_to_pic


@template2pic.handle()
async def _template2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    text_list = ["1", "2", "3", "4"]
    # 设置模板
    # 模板中需要包括样式表
    html = await template_to_html(
        template_path=str(Path(__file__).parent / "templates"),
        template_name="text.html",
        text_list=text_list,
    )
    # 渲染图片
    pic = await html_to_pic(html, viewport={"width": 600, "height": 300})

    a = Image.open(io.BytesIO(pic))
    a.save("template2pic.png", format="PNG")

    await template2pic.finish(MessageSegment.image(pic))


# 使用 md2pic
md2pic = on_command("md2pic")
md_to_pic = require("nonebot_plugin_htmlrender").md_to_pic


@md2pic.handle()
async def _md2pic(bot: Bot, event: MessageEvent):
    from pathlib import Path

    # 如果是直接获取消息内容 需要 unescape
    from nonebot.adapters.cqhttp import unescape
    msg = unescape(str(event.get_message()))

    # css_path 可选
    # pic = await md_to_pic(
    #     md=msg, css_path=str(Path(__file__).parent / "templates" / "markdown.css")
    # )

    pic = await md_to_pic(md=msg)

    a = Image.open(io.BytesIO(pic))
    a.save("md2pic.png", format="PNG")

    await md2pic.finish(MessageSegment.image(pic))
