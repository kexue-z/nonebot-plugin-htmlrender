from __future__ import annotations

from contextlib import asynccontextmanager
from enum import StrEnum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from anyio.to_thread import run_sync
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
from nonebot_plugin_htmlrender.consts import BrowserEngine, RenderBackend
from nonebot_plugin_htmlrender.install import install_browser
from nonebot_plugin_htmlrender.telemetry import track_render
from nonebot_plugin_htmlrender.utils import (
    clean_playwright_cache,
    clear_playwright_env_vars,
    prepare_playwright_env_vars,
    suppress_and_log,
)

from ..base import Renderer, RenderRuntime, RenderSession


class PlaywrightMode(StrEnum):
    REMOTE_CDP = "remote_cdp"
    REMOTE_WS = "remote_ws"
    LOCAL = "local_pw"


class WsVersionRiskLevel(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    BLOCK = "block"


class PlaywrightRender(Renderer[Playwright, Browser]):
    """Playwright-backed renderer.

    Implements the ``Renderer[Playwright, Browser]`` protocol:

    - ``open_runtime`` starts the Playwright subprocess and prepares env vars.
    - ``open_session`` launches or connects a Browser.
    - ``is_alive`` reports whether the Browser connection is healthy.
    - ``get_new_page`` is a Playwright-specific extension that yields a new Page.
    """

    backend: RenderBackend = RenderBackend.PLAYWRIGHT

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        async def _prepare_env() -> None:
            await run_sync(prepare_playwright_env_vars)

        async def _clean_cache() -> None:
            await run_sync(clean_playwright_cache)

        return (_prepare_env, _clean_cache)

    # ------------------------------------------------------------------
    # Renderer protocol
    # ------------------------------------------------------------------

    async def open_runtime(self) -> RenderRuntime[Playwright]:
        """启动 Playwright 子进程并准备环境变量。

        Returns:
            包装了 Playwright 实例的 RenderRuntime。
        """
        async with track_render("playwright.open_runtime", backend=self.backend):
            pw = await async_playwright().start()

            async def _aclose() -> None:
                with suppress_and_log():
                    await pw.stop()
                    logger.info("Playwright stopped.")
                clear_playwright_env_vars()

            return RenderRuntime(backend=self.backend, handle=pw, _aclose=_aclose)

    async def open_session(
        self,
        runtime: RenderRuntime[Playwright],
        **kwargs: Any,
    ) -> RenderSession[Playwright, Browser]:
        """启动或连接一个绑定到给定运行时的浏览器会话。

        Args:
            runtime: 包装了 Playwright 实例的活跃 RenderRuntime。
            **kwargs: 透传给浏览器 launch / connect 调用的额外选项。

        Returns:
            包装了已连接 Browser 实例的 RenderSession。

        Raises:
            RuntimeError: 浏览器无法启动或连接时抛出。
        """
        async with track_render("playwright.open_session", backend=self.backend):
            mode = self._resolve_mode()
            browser = await self._create_browser(runtime.handle, mode, **kwargs)

            async def _aclose() -> None:
                cfg = plugin_config.render_playwright
                if mode == PlaywrightMode.LOCAL and cfg.close_on_exit and browser.is_connected():
                    logger.debug("Closing browser...")
                    with suppress_and_log():
                        await browser.close()
                        logger.info("Browser closed.")

            return RenderSession(runtime=runtime, handle=browser, _aclose=_aclose)

    def is_alive(self, session: RenderSession[Playwright, Browser]) -> bool:
        """检查浏览器会话是否仍处于连接状态。

        Args:
            session: 一个活跃的 RenderSession，其 handle 应为 Browser。

        Returns:
            浏览器已连接则返回 True，否则返回 False。
        """
        browser = session.handle
        return isinstance(browser, Browser) and browser.is_connected()

    # ------------------------------------------------------------------
    # Playwright-specific extension
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def get_new_page(
        self,
        session: RenderSession[Playwright, Browser],
        device_scale_factor: float = 2,
        **kwargs: Any,
    ) -> AsyncIterator[Page]:
        """在给定的浏览器会话中打开一个新页面。

        Args:
            session: 活跃的 RenderSession，其 handle 应为 Browser。
            device_scale_factor: 截图时使用的设备像素比。
            **kwargs: 透传给 browser.new_page() 的额外选项。

        Yields:
            Page: 可立即使用的 Playwright Page 实例。
        """
        async with track_render("playwright.get_new_page", backend=self.backend):
            browser = session.handle
            page = await browser.new_page(device_scale_factor=device_scale_factor, **kwargs)
            async with page:
                yield page

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_mode(self) -> PlaywrightMode:
        cfg = plugin_config.render_playwright
        has_cdp = bool(cfg.connect_cdp.endpoint)
        has_ws = bool(cfg.connect_ws.endpoint)
        if has_cdp and has_ws:
            raise RuntimeError(
                "Invalid configuration: `render_playwright.connect_cdp.endpoint` and "
                "`render_playwright.connect_ws.endpoint` cannot both be set."
            )
        if has_cdp:
            return PlaywrightMode.REMOTE_CDP
        if has_ws:
            return PlaywrightMode.REMOTE_WS
        return PlaywrightMode.LOCAL

    async def _create_browser(
        self,
        pw: Playwright,
        mode: PlaywrightMode,
        **kwargs: Any,
    ) -> Browser:
        cfg = plugin_config.render_playwright
        browser_name = cfg.engine.value

        match mode:
            case PlaywrightMode.REMOTE_CDP:
                if cfg.engine is not BrowserEngine.CHROMIUM:
                    raise RuntimeError(
                        'CDP connection requires `render_playwright.engine="chromium"`.'
                    )
                endpoint = cfg.connect_cdp.endpoint
                if not endpoint:
                    raise RuntimeError("CDP endpoint is empty.")
                logger.info("Connecting to Chromium via CDP (%s)", endpoint)
                options = dict(kwargs)
                options.pop("endpoint_url", None)
                return await pw.chromium.connect_over_cdp(endpoint, **options)

            case PlaywrightMode.REMOTE_WS:
                self._check_ws_version_gate()
                endpoint = cfg.connect_ws.endpoint
                if not endpoint:
                    raise RuntimeError("WebSocket endpoint is empty.")
                logger.info(
                    "Connecting to %s via WebSocket endpoint: %s",
                    browser_name.capitalize(),
                    endpoint,
                )
                options = dict(kwargs)
                options.pop("ws_endpoint", None)
                browser_type = self._get_browser_type(pw, browser_name)
                return await browser_type.connect(endpoint, **options)

            case _:
                browser_type = self._get_browser_type(pw, browser_name)
                options = dict(kwargs)
                if cfg.channel:
                    options["channel"] = cfg.channel.value
                if cfg.proxy_server:
                    options["proxy"] = self._build_proxy(cfg.proxy_server, cfg.proxy_bypass)
                if cfg.launch_args:
                    options["args"] = cfg.launch_args.split()
                if cfg.executable_path:
                    options["executable_path"] = str(cfg.executable_path)
                    return await browser_type.launch(**options)
                return await self._check_env_with_install_retry(pw, **options)

    @staticmethod
    def _build_proxy(
        server: str,
        bypass: str | None = None,
    ) -> dict[str, str]:
        """构建 Playwright 代理选项字典。

        Args:
            server: 代理服务器地址（如 http://host:port 或 socks5://host:port）。
            bypass: 以逗号分隔的不走代理域名列表。

        Returns:
            BrowserType.launch() 可接受的代理选项字典。
        """
        proxy: dict[str, str] = {"server": server}
        if bypass:
            proxy["bypass"] = bypass
        return proxy

    @retry(
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(4),
        wait=wait_fixed(1),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Attempt {retry_state.attempt_number} failed, retrying..."
        ),
    )
    async def _check_env_with_install_retry(
        self,
        pw: Playwright,
        **kwargs: Any,
    ) -> Browser:
        try:
            return await self._check_playwright_env(pw, **kwargs)
        except RuntimeError:
            if plugin_config.render_playwright.skip_browser_install:
                raise
            try:
                await install_browser()
            except Exception as e:
                logger.exception("Browser installation failed.")
                raise RuntimeError(f"install_browser failed: {e}") from e
            raise

    async def _check_playwright_env(
        self,
        pw: Playwright,
        **kwargs: Any,
    ) -> Browser:
        logger.info("Checking Playwright environment...")
        try:
            browser_type = self._get_browser_type(
                pw, plugin_config.render_playwright.engine.value
            )
            browser = await browser_type.launch(**kwargs)
            logger.success("Playwright environment is set up correctly.")
            return browser
        except Exception as e:
            raise RuntimeError(
                "Playwright environment is not set up correctly. "
                "Refer to https://playwright.dev/python/docs/intro#system-requirements"
            ) from e

    @staticmethod
    def _get_browser_type(pw: Playwright, browser_type: str) -> BrowserType:
        return getattr(pw, browser_type)

    # ------------------------------------------------------------------
    # WebSocket version-gate helpers (unchanged logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_semver(version_text: str) -> tuple[int, int, int] | None:
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text)
        if not match:
            return None
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _evaluate_ws_version_risk(
        local: tuple[int, int, int],
        remote: tuple[int, int, int],
    ) -> WsVersionRiskLevel:
        local_major, local_minor, local_patch = local
        remote_major, remote_minor, remote_patch = remote

        if local_major != remote_major:
            return WsVersionRiskLevel.BLOCK

        minor_gap = abs(local_minor - remote_minor)
        if minor_gap >= 2:
            return WsVersionRiskLevel.BLOCK
        if minor_gap == 1:
            return WsVersionRiskLevel.WARNING

        patch_gap = abs(local_patch - remote_patch)
        if patch_gap > 10:
            return WsVersionRiskLevel.WARNING

        return WsVersionRiskLevel.SAFE

    @classmethod
    def _extract_version_from_text(cls, text: str) -> tuple[int, int, int] | None:
        return cls._parse_semver(text)

    @classmethod
    def _extract_version_from_endpoint(
        cls, ws_endpoint: str
    ) -> tuple[int, int, int] | None:
        parsed = urlparse(ws_endpoint)
        query = parse_qs(parsed.query)
        for key in ("playwright_version", "pw_version", "version"):
            value = query.get(key, [])
            if value:
                detected = cls._extract_version_from_text(value[0])
                if detected is not None:
                    return detected

        combined = f"{parsed.path} {parsed.query} {parsed.fragment}"
        match = re.search(
            r"(?:playwright|pw|version)[^0-9]*(\d+)\.(\d+)\.(\d+)",
            combined,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @classmethod
    def _probe_ws_http_version(cls, ws_endpoint: str) -> tuple[int, int, int] | None:
        parsed = urlparse(ws_endpoint)
        if parsed.scheme not in {"ws", "wss"}:
            return None
        http_scheme = "https" if parsed.scheme == "wss" else "http"
        base = f"{http_scheme}://{parsed.netloc}"
        for path in ("/json/version", "/"):
            try:
                request = Request(f"{base}{path}", method="GET")  # noqa: S310
                with urlopen(request, timeout=2) as resp:  # noqa: S310
                    body = resp.read().decode("utf-8", errors="ignore")
                version = cls._extract_version_from_text(body)
                if version is not None:
                    return version
            except Exception as e:
                logger.debug(f"WS version probe failed for {base}{path}: {e!s}")
                continue
        return None

    @classmethod
    def _detect_remote_ws_version(cls, ws_endpoint: str) -> tuple[int, int, int] | None:
        version = cls._extract_version_from_endpoint(ws_endpoint)
        if version is not None:
            return version
        return cls._probe_ws_http_version(ws_endpoint)

    def _check_ws_version_gate(self) -> None:
        ws_endpoint = plugin_config.render_playwright.connect_ws.endpoint
        if not ws_endpoint:
            raise RuntimeError("WS endpoint is empty.")
        try:
            local_version = pkg_version("playwright")
        except PackageNotFoundError as e:
            raise RuntimeError(
                "Local playwright package version is unavailable."
            ) from e

        local = self._parse_semver(local_version)
        if local is None:
            raise RuntimeError("Invalid local playwright version format.")

        remote = self._detect_remote_ws_version(ws_endpoint)
        if remote is None:
            raise RuntimeError(
                "Unable to detect remote Playwright version from WS endpoint: "
                f"{ws_endpoint}"
            )

        remote_version = f"{remote[0]}.{remote[1]}.{remote[2]}"
        risk = self._evaluate_ws_version_risk(local, remote)
        if risk == WsVersionRiskLevel.SAFE:
            logger.info(
                f"WS version gate: SAFE (local={local_version}, remote={remote_version})."
            )
            return
        if risk == WsVersionRiskLevel.WARNING:
            logger.warning(
                f"WS version gate: WARNING (local={local_version}, remote={remote_version})."
            )
            return

        logger.debug(
            f"WS version gate: BLOCK (local={local_version}, remote={remote_version})."
        )
        raise RuntimeError(
            "WS version mismatch is out of allowed range: "
            f"local={local_version}, remote={remote_version}."
        )
