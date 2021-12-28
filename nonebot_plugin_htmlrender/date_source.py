from jinja2.environment import Template
from .browser import get_new_page
from pathlib import Path
import jinja2
from nonebot.log import logger
import markdown
import aiofiles

TEMPLATES_PATH = str(Path(__file__).parent / "templates")

env = jinja2.Environment(
    extensions=["jinja2.ext.loopcontrols"],
    loader=jinja2.FileSystemLoader(TEMPLATES_PATH),
    enable_async=True,
)


async def create_image(
    html: str, wait: int = 0, viewport: dict = {"width": 300, "height": 300}
) -> bytes:
    logger.debug(f"html:\n{html}")
    async with get_new_page(viewport=viewport) as page:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        img_raw = await page.screenshot(full_page=True)
    return img_raw


async def text_to_pic(text: str, css_path: str = None) -> bytes:
    """多行文本转图片

    Args:
        text (str): 纯文本, 可多行
        css_path (str, optional): css文件

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("text.html")
    text_list = text.split("\n")

    return await create_image(
        await template.render_async(
            text_list=text_list,
            css=await read_file(css_path)
            if css_path
            else await read_file(TEMPLATES_PATH + "/text.css"),
        )
    )


async def md_to_pic(md: str = None, md_path: str = None, css_path: str = None) -> bytes:
    """markdown 转 图片

    Args:
        md (str, optional): markdown 文件路径 或 markdown 格式文本
        md_path (str, optional): markdown 文件路径
        css_path (str,  optional): css文件路径. Defaults to None.

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("markdown.html")
    if md:
        return await create_image(
            await template.render_async(
                md=markdown.markdown(md, extensions=["tables", "fenced_code"]),
                css=await read_file(css_path)
                if css_path
                else await read_file(TEMPLATES_PATH + "/github-markdown-light.css"),
            ),
            viewport={"width": 1000, "height": 500},
        )

    elif md_path:
        md = markdown.markdown(
            await read_file(md_path), extensions=["tables", "fenced_code"]
        )
        return await create_image(
            await template.render_async(
                md=md,
                css=await read_file(css_path)
                if css_path
                else await read_file(TEMPLATES_PATH + "/github-markdown-light.css"),
            ),
            viewport={"width": 1000, "height": 500},
        )

    else:
        raise "必须输入 md 或 md_path"


# async def read_md(md_path: str) -> str:
#     async with aiofiles.open(str(Path(md_path).resolve()), mode="r") as f:
#         md = await f.read()
#     return markdown.markdown(md)


async def read_file(path: str) -> str:
    async with aiofiles.open(path, mode="r") as f:
        return await f.read()


async def template_to_html(
    template_path: str,
    template_name: str,
    **kwargs,
) -> str:
    """使用jinja2模板引擎通过html生成图片

    Args:
        template_path (str): 模板路径
        template_name (str): 模板名
        **kwargs: 模板内容
    Returns:
        str: html
    """

    template_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        enable_async=True,
    )
    template = template_env.get_template(template_name)

    return await template.render_async(**kwargs)


async def html_to_pic(html: str, wait: int = 10, **kwargs) -> bytes:
    """html转图片

    Args:
        html (str): html文本
        wait (int, optional): 等待时间. Defaults to 10.

    Returns:
        bytes: 图片, 可直接发送
    """
    logger.debug(f"html:\n{html}")
    async with get_new_page(**kwargs) as page:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        img_raw = await page.screenshot(full_page=True)
    return img_raw
