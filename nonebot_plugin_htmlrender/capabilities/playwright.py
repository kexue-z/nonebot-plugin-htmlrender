"""Stable typed access to a Playwright page owned by the active provider."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from nonebot_plugin_htmlrender._typing import (
    identity_decorator,
    project_method_parameters,
)
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from playwright.async_api import Browser, Page

if TYPE_CHECKING:
    _page_signature = project_method_parameters(Browser.new_page)
else:
    _page_signature = identity_decorator


@runtime_checkable
class PlaywrightAccess(Protocol):
    """Lease raw objects from the provider-owned Playwright runtime."""

    @_page_signature
    def page(
        self,
        **kwargs: Any,
    ) -> AbstractAsyncContextManager[Page]: ...

    def browser(self) -> AbstractAsyncContextManager[Browser]: ...


PLAYWRIGHT: CapabilityKey[PlaywrightAccess] = CapabilityKey(
    "playwright",
    PlaywrightAccess,
)

__all__ = [
    "PLAYWRIGHT",
    "PlaywrightAccess",
]
