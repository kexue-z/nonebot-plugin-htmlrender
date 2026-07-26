"""Typed Playwright page capability resolved at the composition boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, final

from nonebot_plugin_htmlrender.capabilities.playwright import _page_signature
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from playwright.async_api import Browser, Page

    from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver

_OBSERVATION_ATTRIBUTES = {
    "render.backend": "playwright",
    "render.access": "native",
}


@final
class PlaywrightAccessAdapter:
    """Lease raw Playwright pages or the provider-owned native browser."""

    def __init__(
        self,
        leases: ExecutionLeaseProvider[PlaywrightLease],
        observer: OperationObserver,
    ) -> None:
        self._leases = leases
        self._observer = observer

    @_page_signature
    @asynccontextmanager
    async def page(
        self,
        **kwargs: Any,
    ) -> AsyncIterator[Page]:
        """Open a caller-controlled page bound to the leased browser."""
        from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
            PageContext,
        )

        with observe_operation(
            self._observer,
            "playwright.native.page",
            _OBSERVATION_ATTRIBUTES,
        ):
            async with (
                self._leases.lease() as lease,
                PageContext(lease).open(**kwargs) as page,
            ):
                yield page

    @asynccontextmanager
    async def browser(self) -> AsyncIterator[Browser]:
        """Lease the provider-owned native browser without proxying it."""
        from playwright.async_api import Browser  # noqa: PLC0415

        with observe_operation(
            self._observer,
            "playwright.native.browser",
            _OBSERVATION_ATTRIBUTES,
        ):
            async with self._leases.lease() as lease:
                browser = lease.browser
                if not isinstance(browser, Browser):
                    raise RuntimeError("Playwright lease does not expose a Browser.")
                yield browser


__all__ = ["PlaywrightAccessAdapter"]
