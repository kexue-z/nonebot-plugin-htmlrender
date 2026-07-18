"""Stable public contract for Playwright-specific operations.

This module owns the neutral keyword vocabulary shared between callers and
the Playwright adapter, so the capability contract never depends on adapter
modules.  Third-party Playwright types appear only in annotations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from typing_extensions import TypeAlias, TypedDict

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from re import Pattern
    from typing_extensions import Unpack

    from playwright.async_api import (
        Geolocation,
        HttpCredentials,
        Locator,
        Page,
        ProxySettings,
        StorageState,
        ViewportSize,
    )


PathLike: TypeAlias = str | Path


class PageContextKwargs(TypedDict, total=False):
    """Every optional argument of Playwright ``BrowserContext.new_page``."""

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


class GotoKwargs(TypedDict, total=False):
    """Optional arguments of Playwright ``Page.goto``."""

    timeout: float | None
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] | None
    referer: str | None


class LocatorScreenshotKwargs(TypedDict, total=False):
    """Optional arguments of Playwright ``Locator.screenshot``."""

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


class CaptureElementKwargs(TypedDict, total=False):
    """Page, navigation, and locator-screenshot options for element capture."""

    page_kwargs: PageContextKwargs | None
    goto_kwargs: GotoKwargs | None
    screenshot_kwargs: LocatorScreenshotKwargs | None


@runtime_checkable
class PlaywrightPageCapability(Protocol):
    """Raw browser page access bound to the leased Playwright browser."""

    def page(
        self,
        **kwargs: Unpack[PageContextKwargs],
    ) -> AbstractAsyncContextManager[Page]: ...


@runtime_checkable
class PlaywrightCaptureCapability(Protocol):
    """Navigate-and-capture of one selector, built on top of ``page()``."""

    async def capture_element(
        self,
        url: str,
        element: str,
        **kwargs: Unpack[CaptureElementKwargs],
    ) -> bytes: ...


PLAYWRIGHT_PAGE: CapabilityKey[PlaywrightPageCapability] = CapabilityKey(
    "playwright.page",
    PlaywrightPageCapability,
)

PLAYWRIGHT_CAPTURE: CapabilityKey[PlaywrightCaptureCapability] = CapabilityKey(
    "playwright.capture",
    PlaywrightCaptureCapability,
)

__all__ = [
    "PLAYWRIGHT_CAPTURE",
    "PLAYWRIGHT_PAGE",
    "CaptureElementKwargs",
    "GotoKwargs",
    "LocatorScreenshotKwargs",
    "PageContextKwargs",
    "PathLike",
    "PlaywrightCaptureCapability",
    "PlaywrightPageCapability",
]
