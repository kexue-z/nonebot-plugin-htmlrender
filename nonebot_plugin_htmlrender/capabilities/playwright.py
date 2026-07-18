"""Stable public contract for Playwright-specific operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from typing_extensions import Unpack

    from playwright.async_api import Page

    from nonebot_plugin_htmlrender.adapters.playwright.types import (
        CaptureElementKwargs,
        PageContextKwargs,
    )


@runtime_checkable
class PlaywrightCapability(Protocol):
    """Browser page access and selector capture supplied by Playwright."""

    def page(
        self,
        **kwargs: Unpack[PageContextKwargs],
    ) -> AbstractAsyncContextManager[Page]: ...

    async def capture_element(
        self,
        url: str,
        element: str,
        **kwargs: Unpack[CaptureElementKwargs],
    ) -> bytes: ...


PLAYWRIGHT_CAPABILITIES: CapabilityKey[PlaywrightCapability] = CapabilityKey(
    "playwright.capabilities",
    PlaywrightCapability,
)

__all__ = ["PLAYWRIGHT_CAPABILITIES", "PlaywrightCapability"]
