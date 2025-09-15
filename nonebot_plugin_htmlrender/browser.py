from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Optional

from nonebot.log import logger
from playwright.async_api import (
    Browser,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from nonebot_plugin_htmlrender.config import plugin_config
from nonebot_plugin_htmlrender.install import install_browser
from nonebot_plugin_htmlrender.utils import (
    _prepare_playwright_env_vars,
    clean_playwright_cache,
    proxy_settings,
    suppress_and_log,
    with_lock,
)

_browser: Optional[Browser] = None
_playwright: Optional[Playwright] = None


async def _launch(browser_type: str, **kwargs) -> Browser:
    """
    启动浏览器实例。

    Args:
        browser_type (str): 浏览器类型。
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


@asynccontextmanager
async def get_new_page(device_scale_factor: float = 2, **kwargs) -> AsyncIterator[Page]:
    """
    获取一个新的页面的上下文管理器, 这里的 page 默认使用设备缩放因子为 2。

    Args:
        device_scale_factor (float): 设备缩放因子。
        **kwargs: 传递给`browser.new_context`的关键字参数。

    Yields:
        Page: 页面对象。
    """
    ctx = await get_browser()
    page = await ctx.new_page(device_scale_factor=device_scale_factor, **kwargs)
    async with page:
        yield page


@with_lock
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

    return await startup_htmlrender(**kwargs)


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
        f"Connecting to Chromium via CDP ({plugin_config.htmlrender_connect_over_cdp})"
    )
    if _playwright is not None:
        return await _playwright.chromium.connect_over_cdp(**kwargs)
    else:
        raise RuntimeError("Playwright is not initialized")


async def _connect(browser_type: str, **kwargs) -> Browser:
    """
    通过 Playwright 协议连接浏览器。

    Args:
        browser_type (str): 浏览器类型。
        **kwargs: 传递给`playwright.connect`的关键字参数。

    Returns:
        Browser: 启动的浏览器实例。

    Raises:
        RuntimeError: 如果 Playwright 未初始化。
    """
    _browser_cls: BrowserType = getattr(_playwright, browser_type)
    kwargs["ws_endpoint"] = plugin_config.htmlrender_connect
    logger.info(
        f"Connecting to {browser_type.capitalize()} via "
        f"WebSocket endpoint: {plugin_config.htmlrender_connect}"
    )
    if _playwright is not None:
        return await _browser_cls.connect(**kwargs)
    else:
        raise RuntimeError("Playwright is not initialized")


@retry(
    retry=retry_if_exception_type(RuntimeError),
    stop=stop_after_attempt(4),
    wait=wait_fixed(1),
    reraise=True,
    before_sleep=lambda retry_state: logger.warning(
        f"Attempt {retry_state.attempt_number} failed, retrying..."
    ),
)
async def _check_env_with_install_retry(**kwargs):
    try:
        return await check_playwright_env(**kwargs)
    except RuntimeError:
        if plugin_config.htmlrender_ci_mode:
            raise
        try:
            await install_browser()
        except Exception as e:
            logger.error(f"Browser installation failed: {e!s}")
            raise RuntimeError(f"install_browser failed: {e}") from e
        raise


@with_lock
async def startup_htmlrender(**kwargs) -> Browser:
    """
    启动 Playwright 浏览器实例。

    Args:
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Returns:
        Browser: 启动的浏览器实例。
    """
    global _browser, _playwright

    await shutdown_htmlrender()

    if not plugin_config.htmlrender_ci_mode:
        clean_playwright_cache()
        _prepare_playwright_env_vars()

    _playwright = await async_playwright().start()
    logger.debug("Playwright started")

    if (
        plugin_config.htmlrender_browser == "chromium"
        and plugin_config.htmlrender_connect_over_cdp
    ):
        _browser = await _connect_via_cdp(**kwargs)
    elif plugin_config.htmlrender_connect:
        _browser = await _connect(plugin_config.htmlrender_browser, **kwargs)
    else:
        if plugin_config.htmlrender_browser_channel:
            kwargs["channel"] = plugin_config.htmlrender_browser_channel

        if plugin_config.htmlrender_proxy_host:
            kwargs["proxy"] = proxy_settings(plugin_config.htmlrender_proxy_host)

        if plugin_config.htmlrender_browser_args:
            kwargs["args"] = plugin_config.htmlrender_browser_args.split()

        if plugin_config.htmlrender_browser_executable_path:
            kwargs["executable_path"] = plugin_config.htmlrender_browser_executable_path
            try:
                _browser = await _launch(plugin_config.htmlrender_browser, **kwargs)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to launch browser with executable path"
                    f" '{plugin_config.htmlrender_browser_executable_path}': {e}"
                ) from e
        else:
            _browser = await _check_env_with_install_retry(**kwargs)

    return _browser


async def shutdown_htmlrender() -> None:
    is_remote = bool(
        plugin_config.htmlrender_connect or plugin_config.htmlrender_connect_over_cdp
    )
    async with AsyncExitStack() as stack:
        await _schedule_browser_shutdown(stack, is_remote=is_remote)
        await _schedule_playwright_shutdown(stack)
    _clear_globals()


async def _schedule_browser_shutdown(stack: AsyncExitStack, *, is_remote: bool) -> None:
    global _browser
    if not _browser:
        return

    should_close = (not is_remote) and plugin_config.htmlrender_shutdown_browser_on_exit
    if not should_close:
        logger.info(
            "Skipping browser shutdown due to configuration or remote connection."
        )
        return

    browser = _browser
    if not browser.is_connected():
        logger.info("Browser was already disconnected.")
        return

    logger.debug("Disconnecting browser...")

    async def _close_browser():
        with suppress_and_log():
            await browser.close()
            logger.info("Disconnected browser.")

    stack.push_async_callback(_close_browser)


async def _schedule_playwright_shutdown(stack: AsyncExitStack) -> None:
    global _playwright
    if not _playwright:
        return

    pw = _playwright
    logger.debug("Stopping Playwright...")

    async def _stop_pw():
        with suppress_and_log():
            await pw.stop()
            logger.info("Playwright stopped.")

    stack.push_async_callback(_stop_pw)


def _clear_globals() -> None:
    global _browser, _playwright
    _browser = None
    _playwright = None


async def check_playwright_env(**kwargs) -> Browser:
    """
    检查Playwright环境，复用_launch方法避免逻辑重复。

    Args:
        **kwargs: 传递给`playwright.launch`的关键字参数。

    Raises:
        RuntimeError: 如果Playwright环境设置不正确。
    """
    logger.info("Checking Playwright environment...")
    global _browser, _playwright

    try:
        _playwright = await async_playwright().start()
        _browser = await _launch(plugin_config.htmlrender_browser, **kwargs)
        logger.success("Playwright environment is set up correctly.")
        return _browser

    except Exception as e:
        await shutdown_htmlrender()

        raise RuntimeError(
            "Playwright environment is not set up correctly. "
            "Refer to https://playwright.dev/python/docs/intro#system-requirements"
        ) from e
