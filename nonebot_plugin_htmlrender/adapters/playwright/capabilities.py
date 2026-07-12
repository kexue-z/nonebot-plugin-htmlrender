"""Typed Playwright capability resolved at the API/composition boundary.

Everything browser-specific that no longer travels through the neutral
render commands lives here: raw page contexts (navigation, user agent,
headers, browser/page options) and selector capture. Browser modules are
imported lazily to keep the plugin import path light.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing_extensions import Unpack

    from playwright.async_api import Page

    from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease
    from nonebot_plugin_htmlrender.adapters.playwright.types import (
        CaptureElementKwargs,
        PageContextKwargs,
    )
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver

_OBSERVATION_ATTRIBUTES: dict[str, str] = {"render.backend": "playwright"}


@final
class PlaywrightCapabilities:
    """Browser-specific surface: raw page contexts and selector capture."""

    def __init__(
        self,
        leases: ExecutionLeaseProvider[PlaywrightLease],
        observer: OperationObserver,
    ) -> None:
        self._leases = leases
        self._observer = observer

    @asynccontextmanager
    async def page(
        self,
        **kwargs: Unpack[PageContextKwargs],
    ) -> AsyncIterator[Page]:
        """Open a caller-controlled page bound to the leased browser."""
        from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
            open_page_context,
        )

        async with (
            self._leases.lease() as lease,
            open_page_context(lease=lease, **kwargs) as page,
        ):
            yield page

    async def capture_element(
        self,
        url: str,
        element: str,
        **kwargs: Unpack[CaptureElementKwargs],
    ) -> bytes:
        """Navigate to ``url`` and capture ``element`` as image bytes."""
        from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
            capture_html_element,
        )

        async with self._leases.lease() as lease:
            with observe_operation(
                self._observer,
                "playwright.html_render.capture_html_element",
                _OBSERVATION_ATTRIBUTES,
            ):
                return await capture_html_element(url, element, lease=lease, **kwargs)


PLAYWRIGHT_CAPABILITIES: CapabilityKey[PlaywrightCapabilities] = CapabilityKey(
    "playwright.capabilities",
    PlaywrightCapabilities,
)

__all__ = ["PLAYWRIGHT_CAPABILITIES", "PlaywrightCapabilities"]
