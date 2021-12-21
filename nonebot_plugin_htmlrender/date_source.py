from jinja2.environment import Template
from .browser import get_new_page
from pathlib import Path
from typing import Optional, ParamSpecArgs, Union
import jinja2
from nonebot.log import logger
import markdown
import aiofiles

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


async def text_to_pic(text: str, css: Union[Path, str] = None) -> bytes:
    """多行文本转图片

    Args:
        text (str): 纯文本, 可多行
        css (Union[Path,str]): css文件路径或css文本

    Returns:
        bytes: 图片, 可直接发送
    """

    template = env.get_template("text.html")
    text_list = text.split("\n")

    return await create_image(
        await template.render_async(
            text_list=text_list, css=read_css(css) if css else None
        )
    )


async def md_to_pic(md: Union[Path, str], css: Union[Path, str] = None) -> bytes:
    """markdown 转 图片

    Args:
        md (Union[Path, str]): markdown文件路径 或 markdown 格式文本
        css (Union[Path, str], optional): css文件路径 或 css 文本. Defaults to None.

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("markdown.html")

    return await create_image(
        await template.render_async(md=read_md(md), css=read_css(css) if css else None)
    )


async def read_css(css: Union[str, Path]) -> Optional[str]:
    if type(css) == str:
        return css
    elif type(css) == Path:
        async with aiofiles.open(str(css.resolve()), mode="r") as f:
            return await f.read()
    else:
        return None


async def read_md(md: Union[str, Path]) -> str:
    if type(md) == str:
        return md
    elif type(md) == Path:
        async with aiofiles.open(str(md.resolve()), mode="r") as f:
            return await f.read()
