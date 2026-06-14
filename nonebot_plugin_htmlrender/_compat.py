# ruff: noqa: A002, FBT001, FBT002, PTH109
"""Backward-compatible deprecated API surface.

All deprecated top-level functions are defined here. Other modules
(``data_source``, ``browser``, ``__init__``) re-export from this
module so that old import paths keep working.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from os import getcwd
from typing import Any, Literal
from typing_extensions import Unpack, deprecated

from playwright.async_api import Browser

from nonebot_plugin_htmlrender.backend.playwright.operations import (
    read_file as read_file,
)
from nonebot_plugin_htmlrender.backend.playwright.operations import (
    read_tpl as read_tpl,
)
from nonebot_plugin_htmlrender.backend.playwright.runtime import (
    clean_playwright_cache as _clean_playwright_cache,
)
from nonebot_plugin_htmlrender.backend.playwright.runtime import (
    reconcile_legacy_playwright_cache as _reconcile_legacy_playwright_cache,
)
from nonebot_plugin_htmlrender.backend.playwright.types import (
    BrowserSessionKwargs,
    GotoKwargs,
    HtmlPageKwargs,
    LocatorScreenshotKwargs,
    PageContextKwargs,
    TemplatePageKwargs,
)
from nonebot_plugin_htmlrender.render import (
    capture_html_element,
    get_render,
    get_render_context,
    render_html,
    render_markdown,
    render_template,
    render_template_html,
    render_text,
    shutdown_render,
    startup_render,
)


def _require_browser(session: object) -> Browser:
    """从渲染会话中提取 Browser 实例。

    Args:
        session: 渲染会话对象，需包含 ``handle`` 属性。

    Returns:
        会话中的 :class:`Browser` 实例。

    Raises:
        RuntimeError: 当前渲染目标不是 Browser 实例时抛出。
    """
    browser = getattr(session, "handle", None)
    if isinstance(browser, Browser):
        return browser
    raise RuntimeError("Current render target is not a Browser instance.")


@deprecated("`text_to_pic` is deprecated. Use `render_text` instead.")
async def text_to_pic(
    text: str,
    css_path: str = "",
    width: int = 500,
    type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
) -> bytes:
    """已弃用：将文本渲染为图片，请使用 ``render_text``。"""
    return await render_text(
        text,
        css_path=css_path,
        width=width,
        image_type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
    )


@deprecated("`md_to_pic` is deprecated. Use `render_markdown` instead.")
async def md_to_pic(
    md: str = "",
    md_path: str = "",
    css_path: str = "",
    width: int = 500,
    type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
) -> bytes:
    """已弃用：将 Markdown 渲染为图片，请使用 ``render_markdown``。"""
    return await render_markdown(
        md,
        md_path=md_path,
        css_path=css_path,
        width=width,
        image_type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
    )


@deprecated("`template_to_html` is deprecated. Use `render_template_html` instead.")
async def template_to_html(
    template_path: str,
    template_name: str,
    filters: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """已弃用：将模板渲染为 HTML，请使用 ``render_template_html``。"""
    return await render_template_html(
        template_path,
        template_name=template_name,
        filters=filters,
        **kwargs,
    )


@deprecated("`html_to_pic` is deprecated. Use `render_html` instead.")
async def html_to_pic(
    html: str,
    wait: int = 0,
    template_path: str | None = None,
    type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    full_page: bool = True,
    **kwargs: Unpack[HtmlPageKwargs],
) -> bytes:
    """已弃用：将 HTML 渲染为图片，请使用 ``render_html``。"""
    return await render_html(
        html,
        wait=wait,
        template_path=template_path,
        image_type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
        full_page=full_page,
        **kwargs,
    )


@deprecated("`template_to_pic` is deprecated. Use `render_template` instead.")
async def template_to_pic(
    template_path: str,
    template_name: str,
    templates: dict[str, Any],
    filters: dict[str, Any] | None = None,
    pages: TemplatePageKwargs | None = None,
    wait: int = 0,
    type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
) -> bytes:
    """已弃用：将模板渲染为图片，请使用 ``render_template``。"""
    default_pages: TemplatePageKwargs = {
        "viewport": {"width": 500, "height": 10},
        "base_url": f"file://{getcwd()}",
    }
    return await render_template(
        template_path,
        template_name=template_name,
        templates=templates,
        filters=filters,
        pages=pages or default_pages,
        wait=wait,
        image_type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
    )


@deprecated("`capture_element` is deprecated. Use `capture_html_element` instead.")
async def capture_element(
    url: str,
    element: str,
    page_kwargs: PageContextKwargs | None = None,
    goto_kwargs: GotoKwargs | None = None,
    screenshot_kwargs: LocatorScreenshotKwargs | None = None,
) -> bytes:
    """已弃用：捕获页面元素截图，请使用 ``capture_html_element``。"""
    return await capture_html_element(
        url,
        element,
        page_kwargs=page_kwargs,
        goto_kwargs=goto_kwargs,
        screenshot_kwargs=screenshot_kwargs,
    )


@deprecated("`get_new_page` is deprecated. Use `get_render_context` instead.")
@asynccontextmanager
async def get_new_page(
    device_scale_factor: float = 2,
    **kwargs: Unpack[HtmlPageKwargs],
) -> AsyncIterator[object]:
    """已弃用：获取新的浏览器页面，请使用 ``get_render_context``。"""
    async with get_render_context(
        device_scale_factor=device_scale_factor,
        **kwargs,
    ) as page:
        yield page


@deprecated("`get_browser` is deprecated. Use `get_render` instead.")
async def get_browser(**kwargs: Unpack[BrowserSessionKwargs]) -> Browser:
    """已弃用：获取浏览器实例，请使用 ``get_render``。"""
    session = await get_render(**kwargs)
    return _require_browser(session)


@deprecated("`startup_htmlrender` is deprecated. Use `startup_render` instead.")
async def startup_htmlrender(**kwargs: Unpack[BrowserSessionKwargs]) -> Browser:
    """已弃用：启动 HTML 渲染引擎，请使用 ``startup_render``。"""
    session = await startup_render(**kwargs)
    return _require_browser(session)


@deprecated("`shutdown_htmlrender` is deprecated. Use `shutdown_render` instead.")
async def shutdown_htmlrender() -> None:
    """已弃用：关闭 HTML 渲染引擎，请使用 ``shutdown_render``。"""
    await shutdown_render()


@deprecated("`_launch` is deprecated. Use `startup_render` instead.")
async def _launch(
    browser_type: str,
    **kwargs: Unpack[BrowserSessionKwargs],
) -> Browser:
    """已弃用：启动浏览器，请使用 ``startup_render``。"""
    _ = browser_type
    return await startup_htmlrender(**kwargs)


@deprecated(
    "`clean_playwright_cache` from `nonebot_plugin_htmlrender.browser` is deprecated. "
    "Use `nonebot_plugin_htmlrender.backend.playwright.runtime.reconcile_legacy_playwright_cache` instead."
)
def clean_playwright_cache(*, cleanup: bool) -> None:
    """已弃用：清理 Playwright 缓存。"""
    _clean_playwright_cache(cleanup=cleanup)


@deprecated(
    "`reconcile_legacy_playwright_cache` from `nonebot_plugin_htmlrender.browser` "
    "is deprecated. Use "
    "`nonebot_plugin_htmlrender.backend.playwright.runtime.reconcile_legacy_playwright_cache` instead."
)
def reconcile_legacy_playwright_cache(*, cleanup: bool) -> None:
    """已弃用：协调旧版 Playwright 缓存目录。"""
    _reconcile_legacy_playwright_cache(cleanup=cleanup)


__all__ = [
    "_launch",
    "capture_element",
    "clean_playwright_cache",
    "get_browser",
    "get_new_page",
    "html_to_pic",
    "md_to_pic",
    "read_file",
    "read_tpl",
    "reconcile_legacy_playwright_cache",
    "shutdown_htmlrender",
    "startup_htmlrender",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
]
