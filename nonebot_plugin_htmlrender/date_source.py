from .browser import get_new_page
from pathlib import Path
from typing import Union
import jinja2
from nonebot.log import logger

templates_path = Path(__file__).parent / "templates"

env = jinja2.Environment(
    extensions=["jinja2.ext.loopcontrols"],
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
    enable_async=True,
)


async def create_image(html: str, wait: int = 0) -> bytes:
    logger.debug(f"html:\n{html}")
    async with get_new_page(viewport={"width": 300, "height": 300}) as page:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        img_raw = await page.screenshot(full_page=True)
    return img_raw


async def text_to_pic(text: str, css_path: str = None) -> bytes:
    if css_path:
        with open(css_path, "r") as css_file:
            css = css_file.read()
    else:
        css = None
    html = await text_to_html(text, css)
    return await create_image(html)


async def text_to_html(text: str, css: str = None) -> str:
    template = env.get_template("text.html")
    text_list = text.split("\n")
    return await template.render_async(text_list=text_list, css=css)

