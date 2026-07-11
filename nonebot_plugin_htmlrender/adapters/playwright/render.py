from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import partial
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from importlib.util import find_spec
import re
import shutil
from typing import TYPE_CHECKING, Awaitable, Callable, cast
from typing_extensions import Unpack
from urllib.parse import parse_qs, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .types import (
        BrowserLaunchKwargs,
        BrowserSessionKwargs,
        CdpConnectKwargs,
        ProxySettings,
        WsConnectKwargs,
    )

from anyio.to_thread import run_sync
from nonebot.log import logger
from playwright.async_api import (
    Browser,
    BrowserType,
    Playwright,
    async_playwright,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from nonebot_plugin_htmlrender.consts import BrowserEngine, RenderBackend
from nonebot_plugin_htmlrender.utils import suppress_and_log, track_render

from .._backend import (
    BackendAvailability,
    BackendCapability,
    RenderRuntime,
    RenderSession,
)
from .config import PlaywrightConfig, get_playwright_config
from .install import install_browser
from .runtime import (
    clear_playwright_env_vars,
    has_installed_browser,
    prepare_playwright_env_vars,
    reconcile_legacy_playwright_cache,
    record_playwright_runtime_state,
)


class StrEnum(str, Enum):
    pass


class PlaywrightMode(StrEnum):
    REMOTE_CDP = "remote_cdp"
    REMOTE_WS = "remote_ws"
    LOCAL = "local_pw"


@dataclass(slots=True)
class PlaywrightRenderSession(RenderSession):
    """Render session carrying the mode actually selected at connection time."""

    mode: PlaywrightMode


class WsVersionRiskLevel(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    BLOCK = "block"


class PlaywrightBackend:
    """Playwright-backed renderer.

    Implements the ``Backend[Playwright, Browser]`` protocol:

    - ``create_runtime`` starts the Playwright subprocess and prepares env vars.
    - ``create_session`` launches or connects a Browser.
    - ``is_alive`` reports whether the Browser connection is healthy.
    - ``get_render_context`` is a Playwright-specific extension that yields a new Page.
    """

    backend: RenderBackend = RenderBackend.PLAYWRIGHT
    capabilities = frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.HTML_RASTERIZE,
            BackendCapability.TEXT_RENDER,
            BackendCapability.MARKDOWN_RENDER,
            BackendCapability.TEMPLATE_RENDER,
            BackendCapability.TEMPLATE_HTML_RENDER,
            BackendCapability.HTML_ELEMENT_CAPTURE,
        }
    )

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        """返回后端启动前需要执行的异步准备步骤。"""

        async def _prepare_env() -> None:
            await run_sync(prepare_playwright_env_vars)

        async def _clean_cache() -> None:
            await run_sync(
                partial(
                    reconcile_legacy_playwright_cache,
                    cleanup=get_playwright_config().cleanup_legacy_cache,
                )
            )

        async def _record_runtime_state() -> None:
            await run_sync(record_playwright_runtime_state)

        async def _prewarm_filehost() -> None:
            from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
                ensure_filehost_runtime_ready,
            )

            await ensure_filehost_runtime_ready(reason="playwright_startup")

        return (_prepare_env, _clean_cache, _record_runtime_state, _prewarm_filehost)

    async def create_runtime(self) -> RenderRuntime:
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

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: Unpack[BrowserSessionKwargs],
    ) -> PlaywrightRenderSession:
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
            pw = runtime.handle
            if not isinstance(pw, Playwright):
                raise TypeError(f"Expected Playwright handle, got {type(pw).__name__}")
            mode = self._resolve_mode(**kwargs)
            browser = await self._create_browser(pw, mode, **kwargs)

            async def _aclose() -> None:
                cfg = get_playwright_config()
                if (
                    mode == PlaywrightMode.LOCAL
                    and cfg.close_on_exit
                    and browser.is_connected()
                ):
                    logger.debug("Closing browser...")
                    with suppress_and_log():
                        await browser.close()
                        logger.info("Browser closed.")

            return PlaywrightRenderSession(
                runtime=runtime,
                handle=browser,
                _aclose=_aclose,
                mode=mode,
            )

    def is_alive(self, session: RenderSession) -> bool:
        """检查浏览器会话是否仍处于连接状态。

        Args:
            session: 一个活跃的 RenderSession，其 handle 应为 Browser。

        Returns:
            浏览器已连接则返回 True，否则返回 False。
        """
        browser = session.handle
        return isinstance(browser, Browser) and browser.is_connected()

    @staticmethod
    def _normalize_endpoint(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            endpoint = value.strip()
            return endpoint or None
        return str(value)

    def _resolve_mode(self, **kwargs: object) -> PlaywrightMode:
        """根据配置确定 Playwright 连接模式（CDP / WebSocket / 本地）。"""
        cfg = get_playwright_config()
        cdp_endpoint = self._normalize_endpoint(
            cfg.connect_cdp.endpoint or kwargs.get("endpoint_url")
        )
        ws_endpoint = self._normalize_endpoint(
            cfg.connect_ws.endpoint or kwargs.get("endpoint")
        )
        has_cdp = cdp_endpoint is not None
        has_ws = ws_endpoint is not None
        if has_cdp and has_ws:
            raise RuntimeError(
                "Invalid configuration: `render_playwright.connect_cdp.endpoint` and "
                "`render_playwright.connect_ws.endpoint` cannot both be set. "
                "The `endpoint_url` and `endpoint` startup arguments "
                "count as remote endpoints too."
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
        **kwargs: Unpack[BrowserSessionKwargs],
    ) -> Browser:
        """根据连接模式创建浏览器实例。

        Args:
            pw: Playwright 实例。
            mode: 连接模式（CDP / WebSocket / 本地）。
            **kwargs: 透传给浏览器创建方法的额外选项。

        Returns:
            已连接的 Browser 实例。

        Raises:
            RuntimeError: 配置无效或连接失败时。
        """
        cfg = get_playwright_config()
        browser_name = cfg.engine.value

        match mode:
            case PlaywrightMode.REMOTE_CDP:
                if cfg.engine is not BrowserEngine.CHROMIUM:
                    raise RuntimeError(
                        'CDP connection requires `render_playwright.engine="chromium"`.'
                    )
                endpoint = self._normalize_endpoint(
                    cfg.connect_cdp.endpoint or kwargs.get("endpoint_url")
                )
                if not endpoint:
                    raise RuntimeError("CDP endpoint is empty.")
                logger.info(
                    f"Connecting to Chromium via CDP ({self._redact_url(endpoint)})"
                )
                options = cast(
                    "CdpConnectKwargs",
                    {
                        key: value
                        for key, value in kwargs.items()
                        if key != "endpoint_url"
                    },
                )
                chromium = self._get_browser_type(pw, BrowserEngine.CHROMIUM.value)
                return await chromium.connect_over_cdp(endpoint, **options)

            case PlaywrightMode.REMOTE_WS:
                endpoint = self._normalize_endpoint(
                    cfg.connect_ws.endpoint or kwargs.get("endpoint")
                )
                if not endpoint:
                    raise RuntimeError("WS endpoint is empty.")
                self._check_ws_version_gate(endpoint)
                logger.info(
                    "Connecting to "
                    f"{browser_name.capitalize()} via WebSocket endpoint: "
                    f"{self._redact_url(endpoint)}"
                )
                options = cast(
                    "WsConnectKwargs",
                    {key: value for key, value in kwargs.items() if key != "endpoint"},
                )
                browser_type = self._get_browser_type(pw, browser_name)
                return await browser_type.connect(endpoint=endpoint, **options)

            case _:
                browser_type = self._get_browser_type(pw, browser_name)
                options = cast("BrowserLaunchKwargs", dict(kwargs))
                if cfg.channel:
                    options["channel"] = cfg.channel.value
                if cfg.proxy_server:
                    options["proxy"] = self._build_proxy(
                        cfg.proxy_server, cfg.proxy_bypass
                    )
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
    ) -> ProxySettings:
        """构建 Playwright 代理选项字典。

        Args:
            server: 代理服务器地址（如 http://host:port 或 socks5://host:port）。
            bypass: 以逗号分隔的不走代理域名列表。

        Returns:
            BrowserType.launch() 可接受的代理选项字典。
        """
        proxy = cast("ProxySettings", {"server": server})
        if bypass:
            proxy["bypass"] = bypass
        return proxy

    @staticmethod
    def _redact_url(value: str) -> str:
        """脱敏 URL，移除查询参数和认证信息。"""
        try:
            parsed = urlsplit(value)
        except Exception:
            return value

        netloc = parsed.hostname or ""
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))

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
        **kwargs: Unpack[BrowserLaunchKwargs],
    ) -> Browser:
        """检查 Playwright 环境，启动失败时自动安装浏览器并重试。"""
        try:
            return await self._check_playwright_env(pw, **kwargs)
        except RuntimeError:
            if get_playwright_config().skip_browser_install:
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
        **kwargs: Unpack[BrowserLaunchKwargs],
    ) -> Browser:
        """检查 Playwright 环境并尝试启动浏览器。"""
        logger.info("Checking Playwright environment...")
        try:
            browser_type = self._get_browser_type(
                pw, get_playwright_config().engine.value
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
        """从 Playwright 实例获取指定的浏览器类型对象。"""
        return getattr(pw, browser_type)

    @staticmethod
    def _parse_semver(version_text: str) -> tuple[int, int, int] | None:
        """解析语义化版本号字符串为三元组。"""
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text)
        if not match:
            return None
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _evaluate_ws_version_risk(
        local: tuple[int, int, int],
        remote: tuple[int, int, int],
    ) -> WsVersionRiskLevel:
        """评估本地与远程 Playwright 版本差异的风险级别。"""
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
        """从任意文本中提取语义化版本号。"""
        return cls._parse_semver(text)

    @classmethod
    def _extract_version_from_endpoint(
        cls, ws_endpoint: str
    ) -> tuple[int, int, int] | None:
        """从 WebSocket 端点 URL 的查询参数或路径中提取版本号。"""
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
        """通过 HTTP 探测远程 WebSocket 服务的 Playwright 版本。"""
        parsed = urlparse(ws_endpoint)
        if parsed.scheme not in {"ws", "wss"}:
            return None
        http_scheme = "https" if parsed.scheme == "wss" else "http"
        base = f"{http_scheme}://{parsed.netloc}"

        def _probe_path(path: str) -> tuple[int, int, int] | None:
            try:
                request = Request(f"{base}{path}", method="GET")  # noqa: S310
                with urlopen(request, timeout=2) as resp:  # noqa: S310
                    body = resp.read().decode("utf-8", errors="ignore")
                return cls._extract_version_from_text(body)
            except Exception as e:
                logger.debug(f"WS version probe failed for {base}{path}: {e!s}")
                return None

        for path in ("/json/version", "/"):
            version = _probe_path(path)
            if version is not None:
                return version
        return None

    @classmethod
    def _detect_remote_ws_version(cls, ws_endpoint: str) -> tuple[int, int, int] | None:
        """检测远程 WebSocket 端点的 Playwright 版本。"""
        version = cls._extract_version_from_endpoint(ws_endpoint)
        if version is not None:
            return version
        return cls._probe_ws_http_version(ws_endpoint)

    def _check_ws_version_gate(self, endpoint: str | None = None) -> None:
        """检查本地与远程 Playwright 版本兼容性，不兼容时抛出异常。"""
        ws_endpoint = endpoint or get_playwright_config().connect_ws.endpoint
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
            logger.warning(
                "WS version gate: unable to detect remote Playwright version "
                f"from endpoint {self._redact_url(ws_endpoint)!r}; continuing without strict version "
                "compatibility check."
            )
            return

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


def _has_valid_remote_endpoint(endpoint: str, *, schemes: set[str]) -> bool:
    """验证远程端点 URL 的协议和主机是否有效。"""
    parsed = urlparse(endpoint)
    return bool(parsed.scheme in schemes and parsed.netloc)


def _channel_command_candidates(channel: str) -> tuple[str, ...]:
    """获取浏览器 channel 对应的命令行候选列表。"""
    return {
        "chromium": ("chromium",),
        "chrome": ("google-chrome", "chrome", "google-chrome-stable"),
        "chrome-beta": ("google-chrome-beta", "chrome-beta"),
        "chrome-dev": ("google-chrome-unstable", "google-chrome-dev", "chrome-dev"),
        "chrome-canary": ("google-chrome-canary", "chrome-canary"),
        "msedge": ("microsoft-edge", "msedge"),
        "msedge-beta": ("microsoft-edge-beta", "msedge-beta"),
        "msedge-dev": ("microsoft-edge-dev", "msedge-dev"),
        "msedge-canary": ("microsoft-edge-canary", "msedge-canary"),
    }.get(channel, (channel,))


def _has_available_channel_browser(channel: str) -> bool:
    """检查指定 channel 的浏览器是否在 PATH 中可用。"""
    return any(
        shutil.which(candidate) for candidate in _channel_command_candidates(channel)
    )


def is_playwright_backend_available(
    cfg: PlaywrightConfig | None = None,
) -> BackendAvailability:
    """检查 Playwright 后端是否可用。

    依次检查 playwright 包安装状态、配置有效性、远程端点或本地浏览器可用性。

    Args:
        cfg: 已解析的 Playwright 配置；为 ``None`` 时读取当前配置。

    Returns:
        包含可用性状态和原因的 BackendAvailability 对象。
    """
    if find_spec("playwright.async_api") is None:
        return BackendAvailability(
            available=False,
            reason="Python package `playwright` is not installed.",
        )

    if cfg is None:
        try:
            cfg = get_playwright_config()
        except Exception as e:
            return BackendAvailability(
                available=False,
                reason=f"Invalid Playwright config: {e}",
            )

    if cfg.connect_cdp.endpoint:
        if not _has_valid_remote_endpoint(
            cfg.connect_cdp.endpoint,
            schemes={"http", "https", "ws", "wss"},
        ):
            return BackendAvailability(
                available=False,
                reason="Configured CDP endpoint is invalid.",
            )
        return BackendAvailability(available=True)

    if cfg.connect_ws.endpoint:
        if not _has_valid_remote_endpoint(
            cfg.connect_ws.endpoint,
            schemes={"ws", "wss"},
        ):
            return BackendAvailability(
                available=False,
                reason="Configured WebSocket endpoint is invalid.",
            )
        return BackendAvailability(available=True)

    if cfg.executable_path is not None:
        executable_path = cfg.executable_path.expanduser()
        if executable_path.is_file():
            return BackendAvailability(available=True)
        return BackendAvailability(
            available=False,
            reason=f"Configured executable does not exist: {executable_path}",
        )

    if cfg.channel is not None:
        if _has_available_channel_browser(cfg.channel.value):
            return BackendAvailability(available=True)
        return BackendAvailability(
            available=False,
            reason=(
                f"Configured browser channel `{cfg.channel.value}` is not available "
                "on PATH."
            ),
        )

    if not cfg.skip_browser_install:
        return BackendAvailability(available=True)

    if has_installed_browser(cfg.engine):
        return BackendAvailability(available=True)

    return BackendAvailability(
        available=False,
        reason=(
            f"No installed Playwright browser was found for `{cfg.engine.value}` while "
            "`skip_browser_install=true`."
        ),
    )
