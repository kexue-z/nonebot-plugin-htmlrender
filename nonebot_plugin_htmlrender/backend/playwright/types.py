from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from typing_extensions import NotRequired, TypeAlias, TypedDict

if TYPE_CHECKING:
    from collections.abc import Sequence
    from re import Pattern

    from playwright.async_api import (
        FloatRect,
        Geolocation,
        HttpCredentials,
        Locator,
        ProxySettings,
        StorageState,
        ViewportSize,
    )

    from nonebot_plugin_htmlrender.resources import ResourceResolver

    from .models import RenderConfig


PathLike: TypeAlias = str | Path
EnvValue: TypeAlias = str | float | bool


class ClientCertificate(TypedDict, total=False):
    """Playwright 客户端证书配置。"""

    origin: str
    certPath: NotRequired[PathLike]
    cert: NotRequired[bytes]
    keyPath: NotRequired[PathLike]
    key: NotRequired[bytes]
    pfxPath: NotRequired[PathLike]
    pfx: NotRequired[bytes]
    passphrase: NotRequired[str]


class PageContextKwargs(TypedDict, total=False):
    """Playwright ``BrowserContext.new_page`` 的全部可选参数集合。"""

    viewport: ViewportSize | None
    screen: ViewportSize | None
    no_viewport: bool | None
    ignore_https_errors: bool | None
    java_script_enabled: bool | None
    bypass_csp: bool | None
    user_agent: str | None
    locale: str | None
    timezone_id: str | None
    geolocation: Geolocation | None
    permissions: Sequence[str] | None
    extra_http_headers: dict[str, str] | None
    offline: bool | None
    http_credentials: HttpCredentials | None
    device_scale_factor: float | None
    is_mobile: bool | None
    has_touch: bool | None
    color_scheme: Literal["dark", "light", "no-preference", "null"] | None
    reduced_motion: Literal["no-preference", "null", "reduce"] | None
    forced_colors: Literal["active", "none", "null"] | None
    contrast: Literal["more", "no-preference", "null"] | None
    accept_downloads: bool | None
    default_browser_type: str | None
    proxy: ProxySettings | None
    record_har_path: PathLike | None
    record_har_omit_content: bool | None
    record_video_dir: PathLike | None
    record_video_size: ViewportSize | None
    storage_state: StorageState | PathLike | None
    base_url: str | None
    strict_selectors: bool | None
    service_workers: Literal["allow", "block"] | None
    record_har_url_filter: Pattern[str] | str | None
    record_har_mode: Literal["full", "minimal"] | None
    record_har_content: Literal["attach", "embed", "omit"] | None
    client_certificates: list[Any] | None


class HtmlPageKwargs(TypedDict, total=False):
    """HTML 渲染页面可使用的页面上下文参数（不含 ``device_scale_factor``）。"""

    viewport: ViewportSize | None
    screen: ViewportSize | None
    no_viewport: bool | None
    ignore_https_errors: bool | None
    java_script_enabled: bool | None
    bypass_csp: bool | None
    user_agent: str | None
    locale: str | None
    timezone_id: str | None
    geolocation: Geolocation | None
    permissions: Sequence[str] | None
    extra_http_headers: dict[str, str] | None
    offline: bool | None
    http_credentials: HttpCredentials | None
    is_mobile: bool | None
    has_touch: bool | None
    color_scheme: Literal["dark", "light", "no-preference", "null"] | None
    reduced_motion: Literal["no-preference", "null", "reduce"] | None
    forced_colors: Literal["active", "none", "null"] | None
    contrast: Literal["more", "no-preference", "null"] | None
    accept_downloads: bool | None
    default_browser_type: str | None
    proxy: ProxySettings | None
    record_har_path: PathLike | None
    record_har_omit_content: bool | None
    record_video_dir: PathLike | None
    record_video_size: ViewportSize | None
    storage_state: StorageState | PathLike | None
    base_url: str | None
    strict_selectors: bool | None
    service_workers: Literal["allow", "block"] | None
    record_har_url_filter: Pattern[str] | str | None
    record_har_mode: Literal["full", "minimal"] | None
    record_har_content: Literal["attach", "embed", "omit"] | None
    client_certificates: list[Any] | None


class BrowserLaunchKwargs(TypedDict, total=False):
    """Playwright ``BrowserType.launch`` 的全部可选参数集合。"""

    executable_path: PathLike | None
    channel: str | None
    args: Sequence[str] | None
    ignore_default_args: bool | Sequence[str] | None
    handle_sigint: bool | None
    handle_sigterm: bool | None
    handle_sighup: bool | None
    timeout: float | None
    env: dict[str, EnvValue] | None
    headless: bool | None
    proxy: ProxySettings | None
    downloads_path: PathLike | None
    slow_mo: float | None
    traces_dir: PathLike | None
    artifacts_dir: PathLike | None
    chromium_sandbox: bool | None
    firefox_user_prefs: dict[str, EnvValue] | None


class CdpConnectKwargs(TypedDict, total=False):
    """Playwright ``BrowserType.connect_over_cdp`` 的可选参数集合。"""

    timeout: float | None
    slow_mo: float | None
    headers: dict[str, str] | None
    is_local: bool | None


class WsConnectKwargs(TypedDict, total=False):
    """Playwright ``BrowserType.connect`` 的 WebSocket 可选参数集合。"""

    timeout: float | None
    slow_mo: float | None
    headers: dict[str, str] | None
    expose_network: str | None


class BrowserSessionKwargs(
    BrowserLaunchKwargs,
    CdpConnectKwargs,
    WsConnectKwargs,
    total=False,
):
    """启动浏览器会话的统一参数集合，覆盖 launch / CDP / WebSocket 三种模式。"""

    endpoint: str | None
    endpoint_url: str | None


class RenderHtmlKwargs(HtmlPageKwargs, total=False):
    """``render_html`` 的额外渲染参数。"""

    wait: int
    template_path: str | None
    image_type: Literal["jpeg", "png"]
    quality: int | None
    device_scale_factor: float
    screenshot_timeout: float | None
    full_page: bool


class RenderTextKwargs(TypedDict, total=False):
    """``render_text`` 的可选参数。"""

    css_path: str
    width: int
    image_type: Literal["jpeg", "png"]
    quality: int | None
    device_scale_factor: float
    screenshot_timeout: float | None
    render: RenderConfig | None


class RenderMarkdownKwargs(RenderTextKwargs, total=False):
    """``render_markdown`` 的可选参数。"""

    md: str
    md_path: str


class RenderTemplateKwargs(TypedDict, total=False):
    """``render_template`` 的可选参数。"""

    template_name: str | None
    templates: dict[str, Any] | None
    filters: dict[str, Any] | None
    pages: TemplatePageKwargs | None
    wait: int
    image_type: Literal["jpeg", "png"]
    quality: int | None
    device_scale_factor: float
    screenshot_timeout: float | None
    resolve_resources: bool | None
    resource_resolver: ResourceResolver | str | None
    resource_strict: bool


class GotoKwargs(TypedDict, total=False):
    """Playwright ``Page.goto`` 的可选参数集合。"""

    timeout: float | None
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] | None
    referer: str | None


class PageScreenshotKwargs(TypedDict, total=False):
    """Playwright ``Page.screenshot`` 的可选参数集合。"""

    timeout: float | None
    type: Literal["jpeg", "png"] | None
    path: PathLike | None
    quality: int | None
    omit_background: bool | None
    full_page: bool | None
    clip: FloatRect | None
    animations: Literal["allow", "disabled"] | None
    caret: Literal["hide", "initial"] | None
    scale: Literal["css", "device"] | None
    mask: Sequence[Locator] | None
    mask_color: str | None
    style: str | None


class LocatorScreenshotKwargs(TypedDict, total=False):
    """Playwright ``Locator.screenshot`` 的可选参数集合。"""

    timeout: float | None
    type: Literal["jpeg", "png"] | None
    path: PathLike | None
    quality: int | None
    omit_background: bool | None
    animations: Literal["allow", "disabled"] | None
    caret: Literal["hide", "initial"] | None
    scale: Literal["css", "device"] | None
    mask: Sequence[Locator] | None
    mask_color: str | None
    style: str | None


class TemplatePageKwargs(TypedDict, total=False):
    """模板渲染时透传到页面上下文的精简参数集合。"""

    viewport: ViewportSize
    base_url: str
    user_agent: str | None
    extra_http_headers: dict[str, str]


class CaptureElementKwargs(TypedDict, total=False):
    """``capture_html_element`` 三段式参数：页面、导航与定位器截图。"""

    page_kwargs: PageContextKwargs | None
    goto_kwargs: GotoKwargs | None
    screenshot_kwargs: LocatorScreenshotKwargs | None
