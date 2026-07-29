"""Lightweight Playwright availability checks.

This module deliberately avoids importing ``playwright`` or the browser
runtime at module import time so a missing provider extra remains a normal,
diagnosable unavailable state.
"""

from __future__ import annotations

from importlib.util import find_spec
import shutil
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from nonebot_plugin_htmlrender.providers.sdk import ProviderAvailability

if TYPE_CHECKING:
    from .config import PlaywrightConfig


def _playwright_is_installed() -> bool:
    try:
        return (
            find_spec("playwright") is not None
            and find_spec("playwright.async_api") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _has_valid_remote_endpoint(endpoint: str, *, schemes: set[str]) -> bool:
    parsed = urlparse(endpoint)
    return bool(parsed.scheme in schemes and parsed.netloc)


def _channel_command_candidates(channel: str) -> tuple[str, ...]:
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
    return any(
        shutil.which(candidate) for candidate in _channel_command_candidates(channel)
    )


def playwright_availability(config: PlaywrightConfig) -> ProviderAvailability:
    """Return an actionable status without importing the heavy backend first."""
    if not _playwright_is_installed():
        return ProviderAvailability(
            available=False,
            reason=(
                "Optional dependency `playwright` is not installed; install "
                "`nonebot-plugin-htmlrender[playwright]`."
            ),
        )

    if config.connect_cdp.endpoint:
        if not _has_valid_remote_endpoint(
            config.connect_cdp.endpoint,
            schemes={"http", "https", "ws", "wss"},
        ):
            return ProviderAvailability(
                available=False,
                reason="Configured CDP endpoint is invalid.",
            )
        return ProviderAvailability(available=True)

    if config.connect_ws.endpoint:
        if not _has_valid_remote_endpoint(
            config.connect_ws.endpoint,
            schemes={"ws", "wss"},
        ):
            return ProviderAvailability(
                available=False,
                reason="Configured WebSocket endpoint is invalid.",
            )
        return ProviderAvailability(available=True)

    if config.executable_path is not None:
        executable_path = config.executable_path.expanduser()
        if executable_path.is_file():
            return ProviderAvailability(available=True)
        return ProviderAvailability(
            available=False,
            reason=f"Configured executable does not exist: {executable_path}",
        )

    if config.channel is not None:
        if _has_available_channel_browser(config.channel.value):
            return ProviderAvailability(available=True)
        return ProviderAvailability(
            available=False,
            reason=(
                f"Configured browser channel `{config.channel.value}` is not "
                "available on PATH."
            ),
        )

    if not config.skip_browser_install:
        return ProviderAvailability(available=True)

    try:
        from .install_state import (  # noqa: PLC0415
            get_playwright_storage_path,
            has_installed_browser,
        )
    except (ImportError, ModuleNotFoundError, ValueError) as error:
        return ProviderAvailability(
            available=False,
            reason=f"Playwright runtime could not be inspected: {error}",
        )

    if has_installed_browser(
        config.engine,
        storage_path=get_playwright_storage_path(config),
    ):
        return ProviderAvailability(available=True)

    return ProviderAvailability(
        available=False,
        reason=(
            f"No installed Playwright browser was found for `{config.engine.value}` "
            "while `skip_browser_install=true`."
        ),
    )


__all__ = ["playwright_availability"]
