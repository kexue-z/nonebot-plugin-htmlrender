from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from enum import Enum
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


class ConnectionType(str, Enum):
    REMOTE_BROWSER = "remote_browser"
    PLAYWRIGHT_PROTOCOL = "playwright_protocol"
    LOCAL_BROWSER = "local_browser"


class BrowserLifecycleManager:
    def __init__(self) -> None:
        self._browser: Optional[Browser] = None
        self._playwright: Optional[Playwright] = None
        self._connection_type: Optional[ConnectionType] = None

    def _resolve_connection_type(self) -> ConnectionType:
        """
        解析并校验当前配置对应的连接模式。

        规则:
        - `htmlrender_connect_over_cdp` 和 `htmlrender_connect` 不可同时配置
        - CDP 仅支持 Chromium
        - 不做任何连接回退
        """
        has_cdp = bool(plugin_config.htmlrender_connect_over_cdp)
        has_connect = bool(plugin_config.htmlrender_connect)

        if has_cdp and has_connect:
            raise RuntimeError(
                "Invalid configuration: `htmlrender_connect_over_cdp` and "
                "`htmlrender_connect` cannot both be set."
            )

        if has_cdp:
            if plugin_config.htmlrender_browser != "chromium":
                raise RuntimeError(
                    'CDP connection requires `htmlrender_browser="chromium"`.'
                )
            return ConnectionType.REMOTE_BROWSER

        if has_connect:
            return ConnectionType.PLAYWRIGHT_PROTOCOL

        return ConnectionType.LOCAL_BROWSER

    async def _launch(self, browser_type: str, **kwargs) -> Browser:
        """
        启动浏览器实例。

        Args:
            browser_type (str): 浏览器类型。
            **kwargs: 传递给`playwright.launch`的关键字参数。

        Returns:
            Browser: 启动的浏览器实例。
        """
        if self._playwright is None:
            raise RuntimeError("Playwright is not initialized")

        browser_cls: BrowserType = getattr(self._playwright, browser_type)
        logger.opt(colors=True).debug(
            f"<cyan>{browser_type.capitalize()}</cyan> launching with kwargs: {kwargs}"
        )
        logger.opt(colors=True).debug(
            f"Looking for Browser in path: <blue>{browser_cls.executable_path}</blue>"
        )
        return await browser_cls.launch(**kwargs)

    @asynccontextmanager
    async def get_new_page(
        self, device_scale_factor: float = 2, **kwargs
    ) -> AsyncIterator[Page]:
        """
        获取一个新的页面的上下文管理器, 这里的 page 默认使用设备缩放因子为 2。

        Args:
            device_scale_factor (float): 设备缩放因子。
            **kwargs: 传递给`browser.new_context`的关键字参数。

        Yields:
            Page: 页面对象。
        """
        ctx = await self.get_browser()
        page = await ctx.new_page(device_scale_factor=device_scale_factor, **kwargs)
        async with page:
            yield page

    @with_lock
    async def get_browser(self, **kwargs) -> Browser:
        """
        获取浏览器实例。

        Args:
            **kwargs: 传递给`playwright.launch`的关键字参数。

        Returns:
            Browser: 浏览器实例。
        """
        if self._browser and self._browser.is_connected():
            return self._browser

        return await self.startup_htmlrender(**kwargs)

    async def _connect_via_cdp(self, **kwargs) -> Browser:
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
            "Connecting to Chromium via CDP "
            f"({plugin_config.htmlrender_connect_over_cdp})"
        )
        if self._playwright is None:
            raise RuntimeError("Playwright is not initialized")
        return await self._playwright.chromium.connect_over_cdp(**kwargs)

    async def _connect(self, browser_type: str, **kwargs) -> Browser:
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
        if self._playwright is None:
            raise RuntimeError("Playwright is not initialized")

        browser_cls: BrowserType = getattr(self._playwright, browser_type)
        kwargs["ws_endpoint"] = plugin_config.htmlrender_connect
        logger.info(
            f"Connecting to {browser_type.capitalize()} via "
            f"WebSocket endpoint: {plugin_config.htmlrender_connect}"
        )
        return await browser_cls.connect(**kwargs)

    @retry(
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(4),
        wait=wait_fixed(1),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Attempt {retry_state.attempt_number} failed, retrying..."
        ),
    )
    async def _check_env_with_install_retry(self, **kwargs):
        try:
            return await self.check_playwright_env(**kwargs)
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
    async def startup_htmlrender(self, **kwargs) -> Browser:
        """
        启动 Playwright 浏览器实例。

        Args:
            **kwargs: 传递给`playwright.launch`的关键字参数。

        Returns:
            Browser: 启动的浏览器实例。
        """
        await self.shutdown_htmlrender()
        connection_type = self._resolve_connection_type()

        if not plugin_config.htmlrender_ci_mode:
            clean_playwright_cache()
            _prepare_playwright_env_vars()

        self._playwright = await async_playwright().start()
        self._connection_type = connection_type
        logger.debug("Playwright started")

        try:
            if connection_type == ConnectionType.REMOTE_BROWSER:
                self._browser = await self._connect_via_cdp(**kwargs)
            elif connection_type == ConnectionType.PLAYWRIGHT_PROTOCOL:
                self._browser = await self._connect(
                    plugin_config.htmlrender_browser, **kwargs
                )
            else:
                if plugin_config.htmlrender_browser_channel:
                    kwargs["channel"] = plugin_config.htmlrender_browser_channel

                if plugin_config.htmlrender_proxy_host:
                    kwargs["proxy"] = proxy_settings(
                        plugin_config.htmlrender_proxy_host
                    )

                if plugin_config.htmlrender_browser_args:
                    kwargs["args"] = plugin_config.htmlrender_browser_args.split()

                if plugin_config.htmlrender_browser_executable_path:
                    kwargs["executable_path"] = (
                        plugin_config.htmlrender_browser_executable_path
                    )
                    self._browser = await self._launch(
                        plugin_config.htmlrender_browser, **kwargs
                    )
                else:
                    self._browser = await self._check_env_with_install_retry(**kwargs)
        except Exception as e:
            await self.shutdown_htmlrender()
            raise RuntimeError(
                f"Failed to initialize browser in `{connection_type.value}` mode."
            ) from e

        return self._browser

    async def shutdown_htmlrender(self) -> None:
        is_remote = self._connection_type in {
            ConnectionType.REMOTE_BROWSER,
            ConnectionType.PLAYWRIGHT_PROTOCOL,
        }
        async with AsyncExitStack() as stack:
            await self._schedule_browser_shutdown(stack, is_remote=is_remote)
            await self._schedule_playwright_shutdown(stack)
        self._clear_state()

    async def _schedule_browser_shutdown(
        self, stack: AsyncExitStack, *, is_remote: bool
    ) -> None:
        if not self._browser:
            return

        should_close = (
            not is_remote
        ) and plugin_config.htmlrender_shutdown_browser_on_exit
        if not should_close:
            logger.info(
                "Skipping browser shutdown due to configuration or remote connection."
            )
            return

        browser = self._browser
        if not browser.is_connected():
            logger.info("Browser was already disconnected.")
            return

        logger.debug("Disconnecting browser...")

        async def _close_browser():
            with suppress_and_log():
                await browser.close()
                logger.info("Disconnected browser.")

        stack.push_async_callback(_close_browser)

    async def _schedule_playwright_shutdown(self, stack: AsyncExitStack) -> None:
        if not self._playwright:
            return

        pw = self._playwright
        logger.debug("Stopping Playwright...")

        async def _stop_pw():
            with suppress_and_log():
                await pw.stop()
                logger.info("Playwright stopped.")

        stack.push_async_callback(_stop_pw)

    def _clear_state(self) -> None:
        self._browser = None
        self._playwright = None
        self._connection_type = None

    async def check_playwright_env(self, **kwargs) -> Browser:
        """
        检查Playwright环境，复用_launch方法避免逻辑重复。

        Args:
            **kwargs: 传递给`playwright.launch`的关键字参数。

        Raises:
            RuntimeError: 如果Playwright环境设置不正确。
        """
        logger.info("Checking Playwright environment...")

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._launch(
                plugin_config.htmlrender_browser, **kwargs
            )
            logger.success("Playwright environment is set up correctly.")
            return self._browser
        except Exception as e:
            await self.shutdown_htmlrender()
            raise RuntimeError(
                "Playwright environment is not set up correctly. "
                "Refer to https://playwright.dev/python/docs/intro#system-requirements"
            ) from e


_manager = BrowserLifecycleManager()


async def _launch(browser_type: str, **kwargs) -> Browser:
    return await _manager._launch(browser_type, **kwargs)


@asynccontextmanager
async def get_new_page(device_scale_factor: float = 2, **kwargs) -> AsyncIterator[Page]:
    async with _manager.get_new_page(
        device_scale_factor=device_scale_factor, **kwargs
    ) as page:
        yield page


async def get_browser(**kwargs) -> Browser:
    return await _manager.get_browser(**kwargs)


async def _connect_via_cdp(**kwargs) -> Browser:
    return await _manager._connect_via_cdp(**kwargs)


async def _connect(browser_type: str, **kwargs) -> Browser:
    return await _manager._connect(browser_type, **kwargs)


async def _check_env_with_install_retry(**kwargs):
    return await _manager._check_env_with_install_retry(**kwargs)


async def startup_htmlrender(**kwargs) -> Browser:
    return await _manager.startup_htmlrender(**kwargs)


async def shutdown_htmlrender() -> None:
    await _manager.shutdown_htmlrender()


async def _schedule_browser_shutdown(stack: AsyncExitStack, *, is_remote: bool) -> None:
    await _manager._schedule_browser_shutdown(stack, is_remote=is_remote)


async def _schedule_playwright_shutdown(stack: AsyncExitStack) -> None:
    await _manager._schedule_playwright_shutdown(stack)


def _clear_globals() -> None:
    _manager._clear_state()


async def check_playwright_env(**kwargs) -> Browser:
    return await _manager.check_playwright_env(**kwargs)
