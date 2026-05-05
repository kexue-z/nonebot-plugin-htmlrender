"""Backward-compatible import path for Playwright backend.

Deprecated functions that delegate to the modern operations API.
"""

from typing import Any
from typing_extensions import deprecated

from . import operations as _operations

read_file = _operations.read_file
read_tpl = _operations.read_tpl


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def text_to_pic(*args: Any, **kwargs: Any) -> bytes:
    """将纯文本渲染为图片（已弃用，转发至 ``operations.render_text``）。"""
    return await _operations.render_text(*args, **kwargs)


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def md_to_pic(*args: Any, **kwargs: Any) -> bytes:
    """将 Markdown 渲染为图片（已弃用，转发至 ``operations.render_markdown``）。"""
    return await _operations.render_markdown(*args, **kwargs)


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def template_to_html(*args: Any, **kwargs: Any) -> str:
    """将模板渲染为 HTML 字符串（已弃用，转发至 ``operations.render_template_html``）。"""
    return await _operations.render_template_html(*args, **kwargs)


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def html_to_pic(*args: Any, **kwargs: Any) -> bytes:
    """将 HTML 渲染为图片（已弃用，转发至 ``operations.render_html``）。"""
    return await _operations.render_html(*args, **kwargs)


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def template_to_pic(*args: Any, **kwargs: Any) -> bytes:
    """将模板渲染为图片（已弃用，转发至 ``operations.render_template``）。"""
    return await _operations.render_template(*args, **kwargs)


@deprecated(
    "Importing Playwright helpers from "
    "`nonebot_plugin_htmlrender.backend.playwright.data_source` is deprecated. "
    "Import helpers from `nonebot_plugin_htmlrender.backend.playwright.operations` "
    "instead."
)
async def capture_element(*args: Any, **kwargs: Any) -> bytes:
    """截取页面中匹配的 HTML 元素图片（已弃用，转发至 ``operations.capture_html_element``）。"""
    return await _operations.capture_html_element(*args, **kwargs)


__all__ = [
    "capture_element",
    "html_to_pic",
    "md_to_pic",
    "read_file",
    "read_tpl",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
]
