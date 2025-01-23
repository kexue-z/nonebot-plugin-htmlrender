from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from nonebot.log import logger
from playwright.async_api import (
    Browser,
    BrowserType,
    Error,
    Page,
    Playwright,
    async_playwright,
)

from nonebot_plugin_htmlrender.config import BrowserEngineType, plugin_config
from nonebot_plugin_htmlrender.install import install_browser
from nonebot_plugin_htmlrender.utils import proxy_settings, suppress_and_log

_browser: Optional[Browser] = None
_playwright: Optional[Playwright] = None


async def _launch(browser_type: BrowserEngineType, **kwargs) -> Browser:
    """
    启动浏览器实例。

    Args:
        browser_type (BrowserEngineType): 浏览器类型。
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Returns:
        Browser: 启动的浏览器实例。
    """
    _browser_cls: BrowserType = getattr(_playwright, browser_type)
    logger.opt(colors=True).debug(
        f"<cyan>{browser_type.capitalize()}</cyan> launching with kwargs: {kwargs}"
    )
    logger.opt(colors=True).debug(
        f"Looking for Browser in path: <blue>{_browser_cls.executable_path}</blue>"
    )
    return await _browser_cls.launch(**kwargs)


async def init_browser(**kwargs) -> Browser:
    """
    初始化浏览器实例。

    Args:
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Returns:
        Browser: 浏览器实例。

    Raises:
        RuntimeError: 如果浏览器无法启动或安装失败。
    """
    try:
        return await start_browser(**kwargs)
    except (Error, Exception) as e:
        if "Executable doesn't exist" not in str(e):
            raise RuntimeError("无法启动浏览器实例") from e
        try:
            if await install_browser():
                return await start_browser(**kwargs)
            else:
                raise RuntimeError("无法启动浏览器实例且尝试安装失败") from e
        except Exception as e:
            raise RuntimeError("无法启动浏览器实例") from e


@asynccontextmanager
async def get_new_page(device_scale_factor: float = 2, **kwargs) -> AsyncIterator[Page]:
    """
    获取一个新的页面的上下文管理器。

    Args:
        device_scale_factor (float): 设备缩放因子。
        **kwargs: 传递给`browser.new_context`的关键字参数。

    Yields:
        Page: 页面对象。
    """
    ctx = await get_browser()
    page = await ctx.new_page(device_scale_factor=device_scale_factor, **kwargs)
    try:
        yield page
    finally:
        await page.close()


async def get_browser(**kwargs) -> Browser:
    """
    获取浏览器实例。

    Args:
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Returns:
        Browser: 浏览器实例。
    """
    if _browser and _browser.is_connected():
        return _browser

    return await init_browser(**kwargs)


async def _connect_via_cdp(**kwargs) -> Browser:
    """
    通过 CDP 连接 Chromium 浏览器。

    Args:
        **kwargs: 传递给`chromium.connect_over_cdp`的关键字参数。

    Returns:
        Browser: 通过 CDP 连接的浏览器实例。

    Raises:
        RuntimeError: 如果 Playwright 未初始化。
    """
    kwargs["endpoint_url"] = plugin_config.htmlrender_connect_over_cdp
    logger.info(
        f"正在使用 CDP 连接 Chromium({plugin_config.htmlrender_connect_over_cdp})"
    )
    if _playwright is not None:
        return await _playwright.chromium.connect_over_cdp(**kwargs)
    else:
        raise RuntimeError("Playwright 未初始化")


async def start_browser(**kwargs) -> Browser:
    """
    启动 Playwright 浏览器实例。

    Args:
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Returns:
        Browser: 启动的浏览器实例。
    """
    global _browser, _playwright
    _playwright = await async_playwright().start()

    if (
        plugin_config.htmlrender_browser == "chromium"
        and plugin_config.htmlrender_connect_over_cdp
    ):
        return await _connect_via_cdp(**kwargs)

    if plugin_config.htmlrender_browser_channel:
        kwargs["channel"] = plugin_config.htmlrender_browser_channel

    if plugin_config.htmlrender_proxy_host:
        kwargs["proxy"] = proxy_settings(plugin_config.htmlrender_proxy_host)

    if plugin_config.htmlrender_browser_executable_path:
        kwargs["executable_path"] = plugin_config.htmlrender_browser_executable_path

    _browser = await _launch(plugin_config.htmlrender_browser, **kwargs)
    return _browser


async def shutdown_browser() -> None:
    """关闭浏览器和 Playwright 实例。"""
    if _browser:
        with suppress_and_log():
            await _browser.close()
    if _playwright:
        with suppress_and_log():
            await _playwright.stop()
