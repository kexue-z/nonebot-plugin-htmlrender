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


async def text_to_pic(text: str, css_path: str = None, width: int = 500) -> bytes:
    """多行文本转图片

    Args:
        text (str): 纯文本, 可多行
        css_path (str, optional): css文件
        width (int, optional): 图片宽度，默认为 500

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("text.html")

    return await html_to_pic(
        await template.render_async(
            text=text,
            css=await read_file(css_path) if css_path else await read_tpl("text.css"),
        ),
        viewport={"width": width, "height": 10},
    )


async def md_to_pic(
    md: str = None, md_path: str = None, css_path: str = None, width: int = 500
) -> bytes:
    """markdown 转 图片

    Args:
        md (str, optional): markdown 格式文本
        md_path (str, optional): markdown 文件路径
        css_path (str,  optional): css文件路径. Defaults to None.
        width (int, optional): 图片宽度，默认为 500

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("markdown.html")
    if not md:
        if md_path:
            md = await read_file(md_path)
        else:
            raise "必须输入 md 或 md_path"
    logger.debug(md)
    md = markdown.markdown(
        md,
        extensions=[
            "pymdownx.tasklist",
            "tables",
            "fenced_code",
            "codehilite",
            "mdx_math",
        ],
        extension_configs={"mdx_math": {"enable_dollar_delimiter": True}},
    )

    logger.debug(md)
    extra = ""
    if "math/tex" in md:
        katex_css = await read_tpl("katex/katex.min.b64_fonts.css")
        katex_js = await read_tpl("katex/katex.min.js")
        mathtex_js = await read_tpl("katex/mathtex-script-type.min.js")
        extra = (
            f'<style type="text/css">{katex_css}</style>'
            f"<script defer>{katex_js}</script>"
            f"<script defer>{mathtex_js}</script>"
        )

    if css_path:
        css = await read_file(css_path)
    else:
        css = await read_tpl("github-markdown-light.css") + await read_tpl(
            "pygments-default.css"
        )

    return await html_to_pic(
        await template.render_async(md=md, css=css, extra=extra),
        viewport={"width": width, "height": 10},
    )


# async def read_md(md_path: str) -> str:
#     async with aiofiles.open(str(Path(md_path).resolve()), mode="r") as f:
#         md = await f.read()
#     return markdown.markdown(md)


async def read_file(path: str) -> str:
    async with aiofiles.open(path, mode="r") as f:
        return await f.read()


async def read_tpl(path: str) -> str:
    return await read_file(f"{TEMPLATES_PATH}/{path}")


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


async def html_to_pic(html: str, wait: int = 0, **kwargs) -> bytes:
    """html转图片

    Args:
        html (str): html文本
        wait (int, optional): 等待时间. Defaults to 0.

    Returns:
        bytes: 图片, 可直接发送
    """
    # logger.debug(f"html:\n{html}")
    async with get_new_page(**kwargs) as page:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        img_raw = await page.screenshot(full_page=True)
    return img_raw
