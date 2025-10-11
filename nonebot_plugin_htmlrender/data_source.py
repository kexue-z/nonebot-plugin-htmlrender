from os import getcwd
from pathlib import Path
from typing import Any, Literal, Optional, Union

import aiofiles
import jinja2
import markdown
from nonebot.log import logger

from nonebot_plugin_htmlrender.browser import get_new_page

TEMPLATES_PATH = str(Path(__file__).parent / "templates")

env = jinja2.Environment(
    extensions=["jinja2.ext.loopcontrols"],
    loader=jinja2.FileSystemLoader(TEMPLATES_PATH),
    enable_async=True,
)


async def text_to_pic(
    text: str,
    css_path: str = "",
    width: int = 500,
    type: Literal["jpeg", "png"] = "png",
    quality: Union[int, None] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
) -> bytes:
    """多行文本转图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        text (str): 纯文本, 可多行
        css_path (str, optional): css文件
        width (int, optional): 图片宽度，默认为 500
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("text.html")

    return await html_to_pic(
        template_path=f"file://{css_path or TEMPLATES_PATH}",
        html=await template.render_async(
            text=text,
            css=await read_file(css_path) if css_path else await read_tpl("text.css"),
        ),
        viewport={"width": width, "height": 10},
        type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
    )


async def md_to_pic(
    md: str = "",
    md_path: str = "",
    css_path: str = "",
    width: int = 500,
    type: Literal["jpeg", "png"] = "png",
    quality: Union[int, None] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
) -> bytes:
    """markdown 转 图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        md (str, optional): markdown 格式文本
        md_path (str, optional): markdown 文件路径
        css_path (str,  optional): css文件路径. Defaults to None.
        width (int, optional): 图片宽度，默认为 500
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰

    Returns:
        bytes: 图片, 可直接发送
    """
    template = env.get_template("markdown.html")
    if not md:
        if md_path:
            md = await read_file(md_path)
        else:
            raise Exception("md or md_path must be provided")
    logger.debug(md)
    md = markdown.markdown(
        md,
        extensions=[
            "pymdownx.tasklist",
            "tables",
            "fenced_code",
            "codehilite",
            "mdx_math",
            "pymdownx.tilde",
        ],
        extension_configs={"mdx_math": {"enable_dollar_delimiter": True}},
    )

    logger.debug(md)
    extra = ""
    if "math/tex" in md:
        katex_css = await read_tpl("katex/katex.min.b64_fonts.css")
        katex_js = await read_tpl("katex/katex.min.js")
        mhchem_js = await read_tpl("katex/mhchem.min.js")
        mathtex_js = await read_tpl("katex/mathtex-script-type.min.js")
        extra = (
            f'<style type="text/css">{katex_css}</style>'
            f"<script defer>{katex_js}</script>"
            f"<script defer>{mhchem_js}</script>"
            f"<script defer>{mathtex_js}</script>"
        )

    if css_path:
        css = await read_file(css_path)
    else:
        css = await read_tpl("github-markdown-light.css") + await read_tpl(
            "pygments-default.css",
        )

    return await html_to_pic(
        template_path=f"file://{css_path or TEMPLATES_PATH}",
        html=await template.render_async(md=md, css=css, extra=extra),
        viewport={"width": width, "height": 10},
        type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
    )


# async def read_md(md_path: str) -> str:
#     async with aiofiles.open(str(Path(md_path).resolve()), mode="r") as f:
#         md = await f.read()
#     return markdown.markdown(md)


async def read_file(path: str) -> str:
    async with aiofiles.open(path, encoding="UTF8") as f:
        return await f.read()


async def read_tpl(path: str) -> str:
    return await read_file(f"{TEMPLATES_PATH}/{path}")


async def template_to_html(
    template_path: str,
    template_name: str,
    filters: Optional[dict[str, Any]] = None,
    **kwargs,
) -> str:
    """使用jinja2模板引擎通过html生成图片

    Args:
        template_path (str): 模板路径
        template_name (str): 模板名
        filters (Optional[Dict[str, Any]]): 自定义过滤器
        **kwargs: 模板内容
    Returns:
        str: html
    """

    template_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        enable_async=True,
    )

    if filters:
        for filter_name, filter_func in filters.items():
            template_env.filters[filter_name] = filter_func
            logger.debug(f"Custom filter loaded: {filter_name}")

    template = template_env.get_template(template_name)

    return await template.render_async(**kwargs)


async def html_to_pic(
    html: str,
    wait: int = 0,
    template_path: str = f"file://{getcwd()}",
    type: Literal["jpeg", "png"] = "png",
    quality: Union[int, None] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
    full_page: Optional[bool] = True,
    **kwargs,
) -> bytes:
    """html转图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        html (str): html文本
        wait (int, optional): 等待时间. Defaults to 0.
        template_path (str, optional): 模板路径，支持多种URL协议:
            - file:// 本地文件路径 (如 "file:///path/to/template/")
            - http:// 或 https:// 远程URL (用于远程浏览器)
            - data: Data URL
            - about:blank 空白页面
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰
        **kwargs: 传入 page 的参数

    Returns:
        bytes: 图片, 可直接发送
    """
    # logger.debug(f"html:\n{html}")
    async with get_new_page(device_scale_factor, **kwargs) as page:
        page.on("console", lambda msg: logger.debug(f"[Browser Console]: {msg.text}"))
        await page.goto(template_path)
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        return await page.screenshot(
            full_page=full_page,
            type=type,
            quality=quality,
            timeout=screenshot_timeout,
        )


async def template_to_pic(
    template_path: str,
    template_name: str,
    templates: dict[Any, Any],
    filters: Optional[dict[str, Any]] = None,
    pages: Optional[dict[Any, Any]] = None,
    wait: int = 0,
    type: Literal["jpeg", "png"] = "png",
    quality: Union[int, None] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
) -> bytes:
    """使用jinja2模板引擎通过html生成图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        template_path (str): 模板文件的本地路径 (用于jinja2加载模板)
        template_name (str): 模板名
        templates (Dict[Any, Any]): 模板内参数 如: {"name": "abc"}
        filters (Optional[Dict[str, Any]]): 自定义过滤器
        pages (Optional[Dict[Any, Any]]): 网页参数，支持以下字段:
            - base_url: 浏览器页面的基础URL，用于解析相对路径。
              对于本地浏览器使用 file:// 协议，
              对于远程浏览器可使用 http:// 或 https:// 协议。
              默认为 f"file://{getcwd()}"
            - viewport: 视口大小，默认为 {"width": 500, "height": 10}
        wait (int, optional): 网页载入等待时间. Defaults to 0.
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰
    Returns:
        bytes: 图片 可直接发送
    """
    if pages is None:
        pages = {
            "viewport": {"width": 500, "height": 10},
            "base_url": f"file://{getcwd()}",
        }

    template_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        enable_async=True,
    )

    if filters:
        for filter_name, filter_func in filters.items():
            template_env.filters[filter_name] = filter_func
            logger.debug(f"Custom filter loaded: {filter_name}")

    template = template_env.get_template(template_name)

    # Use base_url from pages if provided, otherwise use file:// URL from template_path
    # This allows remote browsers to use http/https URLs
    # while local browsers use file:// URLs
    page_base_url = pages.get("base_url", f"file://{template_path}")

    return await html_to_pic(
        template_path=page_base_url,
        html=await template.render_async(**templates),
        wait=wait,
        type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
        **pages,
    )


async def capture_element(
    url: str,
    element: str,
    page_kwargs: Optional[dict] = None,
    goto_kwargs: Optional[dict] = None,
    screenshot_kwargs: Optional[dict] = None,
) -> bytes:
    """捕获网页中指定元素的截图, 通过CSS选择器或XPath表达式指定元素。

    Args:
        url: 目标网页URL
        element: CSS选择器或XPath表达式
        page_kwargs: 传递给get_new_page的参数
        goto_kwargs: 传递给page.goto方法的额外参数
        screenshot_kwargs: 传递给screenshot方法的额外参数

    Returns:
        bytes: 元素截图数据
    """
    page_kwargs = page_kwargs or {}
    goto_kwargs = goto_kwargs or {}
    screenshot_kwargs = screenshot_kwargs or {}

    async with get_new_page(**page_kwargs) as page:
        page.on(
            "console",
            lambda msg: logger.opt(colors=True).debug(
                f"<cyan>[Browser Console]</cyan> {msg.text}"
            ),
        )
        await page.goto(url, **goto_kwargs)
        return await page.locator(element).screenshot(**screenshot_kwargs)
