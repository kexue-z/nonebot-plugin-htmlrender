from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import partial
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from playwright.async_api import ProxySettings

import anyio
from anyio import CapacityLimiter
from anyio.to_thread import run_sync
from exceptiongroup import BaseExceptionGroup
from nonebot.log import logger
from playwright.async_api import (
    Browser,
    BrowserType,
    Playwright,
    async_playwright,
)

from nonebot_plugin_htmlrender.providers.sdk import PLAYWRIGHT_PROVIDER_ID, EngineId
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

from .config import BrowserEngine
from .install import install_browser
from .install_state import (
    reconcile_legacy_playwright_cache,
    record_playwright_runtime_state,
)
from .spawn import DRIVER_SPAWN_COORDINATOR

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver

    from .config import PlaywrightConfig

_WS_PROBE_DEADLINE_SECONDS = 4.0


class StrEnum(str, Enum):
    pass


class LaunchFailureKind(StrEnum):
    """Stable categories for browser launch/connect failures."""

    INSTALL_REQUIRED = "install_required"
    CONFIGURATION = "configuration"
    REMOTE_CONNECT = "remote_connect"
    VERSION_INCOMPATIBLE = "version_incompatible"
    RUNTIME_DEPENDENCY = "runtime_dependency"


_INSTALL_REQUIRED_MARKERS = (
    "Executable doesn't exist",
    "download new browsers",
)
_RUNTIME_DEPENDENCY_MARKERS = (
    "missing dependencies",
    "install-deps",
    "shared libraries",
)


def _classify_local_launch_failure(error: BaseException) -> LaunchFailureKind:
    message = str(error)
    if any(marker in message for marker in _INSTALL_REQUIRED_MARKERS):
        return LaunchFailureKind.INSTALL_REQUIRED
    if any(marker in message for marker in _RUNTIME_DEPENDENCY_MARKERS):
        return LaunchFailureKind.RUNTIME_DEPENDENCY
    return LaunchFailureKind.CONFIGURATION


class PlaywrightMode(StrEnum):
    REMOTE_CDP = "remote_cdp"
    REMOTE_WS = "remote_ws"
    LOCAL = "local_pw"


@dataclass(slots=True)
class PlaywrightLease:
    """Provider-local Playwright process and browser connection."""

    playwright: Playwright
    browser: Browser
    mode: PlaywrightMode


class WsVersionRiskLevel(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    BLOCK = "block"


class PlaywrightEngine:
    """Own Playwright resources using one explicitly injected configuration."""

    backend: EngineId = PLAYWRIGHT_PROVIDER_ID

    def __init__(
        self,
        config: PlaywrightConfig,
        *,
        operation_observer: OperationObserver,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self._operation_observer = operation_observer

    async def create_lease(self) -> PlaywrightLease:
        """Prepare the environment and create one process/browser lease."""
        playwright: Playwright | None = None
        try:
            await run_sync(
                partial(
                    reconcile_legacy_playwright_cache,
                    self._config,
                    cleanup=self._config.cleanup_legacy_cache,
                )
            )
            await run_sync(record_playwright_runtime_state, self._config)

            with observe_operation(
                self._operation_observer,
                "playwright.open_runtime",
                {"render.backend": self.backend},
            ):
                # The coordinator is the process-wide owner of the browser
                # store env var; it scopes the snapshot to this driver spawn
                # without serializing browser lifetime or binding a backend.
                async with DRIVER_SPAWN_COORDINATOR.browsers_path_guard(self._config):
                    playwright = await async_playwright().start()
            with observe_operation(
                self._operation_observer,
                "playwright.open_session",
                {"render.backend": self.backend},
            ):
                mode = self._resolve_mode()
                browser = await self._create_browser(playwright, mode)
        except BaseException as error:
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception as stop_error:
                    raise BaseExceptionGroup(
                        "Playwright lease creation failed and the spawned "
                        "driver could not be stopped.",
                        [error, stop_error],
                    ) from None
            raise
        return PlaywrightLease(
            playwright=playwright,
            browser=browser,
            mode=mode,
        )

    def is_alive(self, lease: PlaywrightLease) -> bool:
        return lease.browser.is_connected()

    async def close_lease(self, lease: PlaywrightLease) -> None:
        """Close browser and driver separately, aggregating every failure.

        Both steps always run so a browser-close failure cannot leak the
        driver process; the caller receives every teardown error and decides
        whether the close may be retried.
        """
        errors: list[Exception] = []
        if (
            lease.mode == PlaywrightMode.LOCAL
            and self._config.close_on_exit
            and lease.browser.is_connected()
        ):
            logger.debug("Closing browser...")
            try:
                await lease.browser.close()
            except Exception as error:
                errors.append(error)
            else:
                logger.info("Browser closed.")
        try:
            await lease.playwright.stop()
        except Exception as error:
            errors.append(error)
        else:
            logger.info("Playwright stopped.")
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("Playwright teardown failed.", errors)

    @staticmethod
    def _normalize_endpoint(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            endpoint = value.strip()
            return endpoint or None
        return str(value)

    def _resolve_mode(self) -> PlaywrightMode:
        """Select the Playwright connection mode from configuration."""
        cfg = self._config
        has_cdp = self._normalize_endpoint(cfg.connect_cdp.endpoint) is not None
        has_ws = self._normalize_endpoint(cfg.connect_ws.endpoint) is not None
        if has_cdp and has_ws:
            raise RuntimeError(
                "Invalid configuration: "
                "`render.provider_config.connect_cdp.endpoint` and "
                "`render.provider_config.connect_ws.endpoint` cannot both be set."
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
    ) -> Browser:
        """Create the browser for the resolved connection mode."""
        cfg = self._config
        browser_name = cfg.engine.value

        match mode:
            case PlaywrightMode.REMOTE_CDP:
                if cfg.engine is not BrowserEngine.CHROMIUM:
                    raise RuntimeError(
                        "CDP connection requires "
                        '`render.provider_config.engine="chromium"`.'
                    )
                endpoint = self._normalize_endpoint(cfg.connect_cdp.endpoint)
                if not endpoint:
                    raise RuntimeError("CDP endpoint is empty.")
                logger.info("Connecting to Chromium via CDP.")
                chromium = self._get_browser_type(pw, BrowserEngine.CHROMIUM.value)
                try:
                    return await chromium.connect_over_cdp(endpoint)
                except Exception as error:
                    self._log_launch_failure(
                        LaunchFailureKind.REMOTE_CONNECT, mode, attempt=1
                    )
                    raise RuntimeError(
                        "Playwright remote CDP connection failed "
                        f"({LaunchFailureKind.REMOTE_CONNECT.value})."
                    ) from error

            case PlaywrightMode.REMOTE_WS:
                endpoint = self._normalize_endpoint(cfg.connect_ws.endpoint)
                if not endpoint:
                    raise RuntimeError("WS endpoint is empty.")
                await self._check_ws_version_gate(endpoint)
                logger.info(f"Connecting to {browser_name.capitalize()} via WebSocket.")
                browser_type = self._get_browser_type(pw, browser_name)
                try:
                    return await browser_type.connect(endpoint=endpoint)
                except Exception as error:
                    self._log_launch_failure(
                        LaunchFailureKind.REMOTE_CONNECT, mode, attempt=1
                    )
                    raise RuntimeError(
                        "Playwright remote WebSocket connection failed "
                        f"({LaunchFailureKind.REMOTE_CONNECT.value})."
                    ) from error

            case _:
                browser_type = self._get_browser_type(pw, browser_name)
                channel = cfg.channel.value if cfg.channel else None
                proxy = (
                    self._build_proxy(cfg.proxy_server, cfg.proxy_bypass)
                    if cfg.proxy_server
                    else None
                )
                args = cfg.launch_args.split() if cfg.launch_args else None
                if cfg.executable_path:
                    return await browser_type.launch(
                        executable_path=str(cfg.executable_path),
                        channel=channel,
                        proxy=proxy,
                        args=args,
                    )
                if channel is None and proxy is None and args is None:
                    return await self._launch_local_browser(pw)
                return await self._launch_local_browser(
                    pw,
                    channel=channel,
                    proxy=proxy,
                    args=args,
                )

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
        proxy: ProxySettings = {"server": server}
        if bypass:
            proxy["bypass"] = bypass
        return proxy

    @staticmethod
    def _log_launch_failure(
        kind: LaunchFailureKind,
        mode: PlaywrightMode,
        *,
        attempt: int,
    ) -> None:
        # Only the stable category, mode, and attempt counter — no endpoint,
        # exception payload, or install source.
        logger.warning(
            "Playwright browser launch failed "
            f"(category={kind.value}, mode={mode.value}, attempt={attempt})."
        )

    async def _launch_local_browser(
        self,
        pw: Playwright,
        *,
        channel: str | None = None,
        proxy: ProxySettings | None = None,
        args: list[str] | None = None,
    ) -> Browser:
        """Launch locally; only a definite install-required failure installs.

        One installation and one retry at most. Configuration, runtime
        dependency, and any other failure translate immediately without
        touching the browser store.
        """
        browser_type = self._get_browser_type(pw, self._config.engine.value)
        try:
            return await browser_type.launch(channel=channel, proxy=proxy, args=args)
        except Exception as error:
            kind = _classify_local_launch_failure(error)
            self._log_launch_failure(kind, PlaywrightMode.LOCAL, attempt=1)
            if (
                kind is not LaunchFailureKind.INSTALL_REQUIRED
                or self._config.skip_browser_install
            ):
                raise RuntimeError(
                    f"Playwright browser launch failed ({kind.value}). Refer to "
                    "https://playwright.dev/python/docs/intro#system-requirements"
                ) from error
        try:
            await install_browser(self._config)
        except Exception as error:
            raise RuntimeError(
                "Playwright browser installation failed after an "
                "install-required launch failure."
            ) from error
        try:
            return await browser_type.launch(channel=channel, proxy=proxy, args=args)
        except Exception as error:
            kind = _classify_local_launch_failure(error)
            self._log_launch_failure(kind, PlaywrightMode.LOCAL, attempt=2)
            raise RuntimeError(
                "Playwright browser launch failed after one install retry "
                f"({kind.value})."
            ) from error

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
    def _probe_ws_paths(cls, base: str) -> tuple[int, int, int] | None:
        """Blocking HTTP probe over the version endpoints of one origin."""
        for path in ("/json/version", "/"):
            try:
                request = Request(f"{base}{path}", method="GET")  # noqa: S310
                with urlopen(request, timeout=2) as resp:  # noqa: S310
                    body = resp.read().decode("utf-8", errors="ignore")
            except Exception as error:
                logger.debug(
                    "WS version probe request failed: {}",
                    type(error).__name__,
                )
                continue
            version = cls._extract_version_from_text(body)
            if version is not None:
                return version
        return None

    @classmethod
    async def _probe_ws_http_version(
        cls,
        ws_endpoint: str,
    ) -> tuple[int, int, int] | None:
        """Probe the remote Playwright version without blocking the loop.

        The stdlib HTTP probe runs on a bounded worker hop under one unified
        deadline covering both probed paths; cancellation abandons the hop
        instead of blocking the event loop.
        """
        parsed = urlparse(ws_endpoint)
        if parsed.scheme not in {"ws", "wss"}:
            return None
        http_scheme = "https" if parsed.scheme == "wss" else "http"
        base = f"{http_scheme}://{parsed.netloc}"
        try:
            with anyio.fail_after(_WS_PROBE_DEADLINE_SECONDS):
                return await run_sync(
                    partial(cls._probe_ws_paths, base),
                    limiter=CapacityLimiter(1),
                    abandon_on_cancel=True,
                )
        except TimeoutError:
            logger.debug("WS version probe exceeded its deadline.")
            return None

    @classmethod
    async def _detect_remote_ws_version(
        cls,
        ws_endpoint: str,
    ) -> tuple[int, int, int] | None:
        """检测远程 WebSocket 端点的 Playwright 版本。"""
        version = cls._extract_version_from_endpoint(ws_endpoint)
        if version is not None:
            return version
        return await cls._probe_ws_http_version(ws_endpoint)

    async def _check_ws_version_gate(self, endpoint: str | None = None) -> None:
        """检查本地与远程 Playwright 版本兼容性，不兼容时抛出异常。"""
        ws_endpoint = endpoint or self._config.connect_ws.endpoint
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

        remote = await self._detect_remote_ws_version(ws_endpoint)
        if remote is None:
            logger.warning(
                "WS version gate: unable to detect the remote Playwright "
                "version; continuing without strict version compatibility "
                "check."
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


__all__ = [
    "PlaywrightEngine",
    "PlaywrightLease",
    "PlaywrightMode",
    "WsVersionRiskLevel",
]
