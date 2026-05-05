from pathlib import Path
from typing import Any

from nonebot import get_plugin_config
from nonebot.compat import model_validator
from nonebot.log import logger
import nonebot_plugin_localstore as store
from pydantic import BaseModel, Field, field_validator

from nonebot_plugin_htmlrender.consts import (
    BrowserEngine,
    ChromiumChannel,
    RenderBackend,
)

plugin_cache_dir: Path = store.get_plugin_cache_dir()
plugin_config_dir: Path = store.get_plugin_config_dir()
plugin_data_dir: Path = store.get_plugin_data_dir()


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class RemoteWSConfig(BaseModel):
    """Remote Playwright protocol connection (WebSocket)."""

    endpoint: str | None = Field(default=None)
    """WebSocket endpoint used by `BrowserType.connect()`.

    See [Playwright docs](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect).
    """


class RemoteCDPConfig(BaseModel):
    """Remote CDP connection for Chromium-based browsers."""

    endpoint: str | None = Field(default=None)
    """CDP endpoint URL used by `BrowserType.connect_over_cdp()`.

    Accepts `http(s)://...` or `ws(s)://...`. See
    [Playwright docs](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp).
    """


class PlaywrightConfig(BaseModel):
    """Playwright backend configuration.

    Notes:
        - `channel` and `connect_cdp` are only available when `engine="chromium"`.
        - Only one remote mode can be enabled at a time: WebSocket or CDP.
    """

    engine: BrowserEngine = Field(default=BrowserEngine.CHROMIUM)
    """Browser engine to use (`chromium`/`firefox`/`webkit`).

    See [Playwright browsers](https://playwright.dev/python/docs/browsers).
    """

    channel: ChromiumChannel | None = Field(default=None)
    """Browser distribution channel for Chromium launches.

    See [BrowserType.launch](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch).
    """

    executable_path: Path | None = Field(default=None)
    """Path to a browser executable to run instead of the bundled one.

    See [BrowserType.launch](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch).
    """

    launch_args: str | None = Field(default=None)
    """Extra CLI arguments passed to the browser process.

    See [BrowserType.launch](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch).
    """

    proxy_server: str | None = Field(default=None)
    """Proxy server for browser network requests (`http(s)://...` or `socks5://...`).

    See [BrowserType.launch](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch).
    """

    proxy_bypass: str | None = Field(default=None)
    """Comma-separated domains to bypass proxy.

    See [BrowserType.launch](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch).
    """

    connect_ws: RemoteWSConfig = Field(default_factory=RemoteWSConfig)
    """Remote Playwright protocol (WebSocket) connect settings.

    See [BrowserType.connect](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect).
    """

    connect_cdp: RemoteCDPConfig = Field(default_factory=RemoteCDPConfig)
    """Remote CDP connect settings (Chromium-only).

    See [BrowserType.connect_over_cdp](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp).
    """

    install_mirror: str | None = Field(default=None)
    """Download host override for browser binaries (`PLAYWRIGHT_DOWNLOAD_HOST`).

    See [Download from artifact repository](https://playwright.dev/docs/browsers#download-from-artifact-repository).
    """

    install_proxy: str | None = Field(default=None)
    """Proxy for downloading browser binaries.

    See [Install behind a firewall or a proxy](https://playwright.dev/docs/browsers#install-behind-a-firewall-or-a-proxy).
    """

    skip_browser_install: bool = Field(default=False)
    """Skip Playwright browser installation step (plugin behavior)."""

    close_on_exit: bool = Field(default=True)
    """Whether to close the `Browser` instance on plugin shutdown."""

    @field_validator("executable_path", mode="before")
    @classmethod
    def _normalize_executable_path(cls, v: Any) -> Any:
        """Normalize `executable_path` input.

        Treat empty/placeholder values (`""`, `"."`, `Path()`) as `None`, so users can
        explicitly disable the setting without breaking validation.
        """
        if v is None:
            return None

        if isinstance(v, Path):
            return None if v == Path() else v

        s = v.strip() if isinstance(v, str) else str(v).strip()
        if not s or s == ".":
            return None
        return s

    @model_validator(mode="after")
    @classmethod
    def validate_playwright_config(cls, data: Any) -> Any:
        """Cross-field validation for Playwright options.

        Enforces:
        - `engine`/`channel` values are within enums
        - `channel` is only allowed for Chromium
        - exactly one remote mode can be enabled (`connect_ws` vs `connect_cdp`)
        - CDP requires Chromium
        """
        engine_raw = _get(data, "engine", BrowserEngine.CHROMIUM)
        channel_raw = _get(data, "channel")
        connect_ws = _get(data, "connect_ws")
        connect_cdp = _get(data, "connect_cdp")

        ws_endpoint = _get(connect_ws, "endpoint")
        cdp_endpoint = _get(connect_cdp, "endpoint")

        try:
            engine = BrowserEngine(engine_raw)
        except ValueError:
            allowed = tuple(v.value for v in BrowserEngine)
            raise ValueError(
                f"[playwright] invalid engine: {engine_raw!r}. Must be one of {allowed}"
            ) from None

        if channel_raw is not None:
            if engine is not BrowserEngine.CHROMIUM:
                raise ValueError(
                    "[playwright] `channel` is only supported when `engine='chromium'`."
                )
            try:
                ChromiumChannel(channel_raw)
            except ValueError:
                allowed = tuple(v.value for v in ChromiumChannel)
                raise ValueError(
                    f"[playwright] invalid channel: {channel_raw!r}. Must be one of {allowed}"
                ) from None

        if ws_endpoint and cdp_endpoint:
            raise ValueError(
                "[playwright] only one remote mode can be enabled at a time: "
                "`render_playwright.connect_ws.endpoint` or `render_playwright.connect_cdp.endpoint`."
            )

        if cdp_endpoint and engine is not BrowserEngine.CHROMIUM:
            raise ValueError(
                "[playwright] CDP connection requires `render_playwright.engine='chromium'`."
            )

        return data


class SkiaConfig(BaseModel):
    enabled: bool = Field(default=True)
    """Enable Skia backend (if available)."""


class PillowConfig(BaseModel):
    enabled: bool = Field(default=True)
    """Enable Pillow backend (if available)."""


class Config(BaseModel):
    """Main plugin configuration model.

    Fields are loaded via `nonebot.get_plugin_config(Config)` and usually map to
    `plugin_name_*` keys in NoneBot config.
    """

    render_backend: RenderBackend | None = Field(default=None)
    """Select render backend implementation."""

    render_storage_path: Path = Field(default=plugin_data_dir)
    """Persistent storage directory used by the plugin."""

    render_cache_path: Path = Field(default=plugin_cache_dir)
    """Cache directory used by the plugin."""

    render_config_path: Path = Field(default=plugin_config_dir)
    """Directory for storing generated/auxiliary configuration files."""

    render_playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    """Playwright backend configuration."""

    render_skia: SkiaConfig = Field(default_factory=SkiaConfig)
    """Skia backend configuration."""

    render_pillow: PillowConfig = Field(default_factory=PillowConfig)
    """Pillow backend configuration."""

    @model_validator(mode="after")
    @classmethod
    def validate_render_backend(cls, data: Any) -> Any:
        """Validate `render_backend` is within `RenderBackend` enum."""
        raw = _get(data, "render_backend", None)

        if raw is None:
            logger.info(
                "[htmlrender] render_backend is not set, no backend will be started."
            )
            return data

        try:
            RenderBackend(raw)
        except ValueError:
            allowed = tuple(v.value for v in RenderBackend)
            raise ValueError(
                f"invalid render_backend: {raw!r}. Must be one of {allowed}"
            ) from None

        return data


plugin_config = get_plugin_config(Config)

if (
    plugin_config.render_backend is RenderBackend.PLAYWRIGHT
    and plugin_config.render_playwright.skip_browser_install
):
    logger.info("[playwright] skip Playwright browser install enabled.")
