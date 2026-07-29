from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from anyio.lowlevel import checkpoint
from playwright.async_api import Browser, Page, Playwright

from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PlaywrightAccessAdapter,
)
from nonebot_plugin_htmlrender.adapters.playwright.render import (
    PlaywrightLease,
    PlaywrightMode,
)
from nonebot_plugin_htmlrender.capabilities import (
    PLAYWRIGHT,
    PlaywrightAccess,
)
from tests.adapters.conftest import RecordingOperationObserver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.rendering.errors import RenderingError


@dataclass(slots=True)
class _LeaseState:
    lease: PlaywrightLease
    alive: bool = True


def test_playwright_capability_key_identity() -> None:
    assert PLAYWRIGHT.name == "playwright"
    assert PLAYWRIGHT.interface is PlaywrightAccess


@contextmanager
def _translate(
    operation: str,
    error_type: type[RenderingError],
) -> Iterator[None]:
    try:
        yield
    except Exception as error:
        raise error_type(f"{operation} failed.", source=error) from error


def _capability(
    *,
    close: Callable[[PlaywrightLease], Awaitable[None]],
) -> tuple[
    PlaywrightAccessAdapter,
    _LeaseState,
    ExecutionLeaseProvider[PlaywrightLease],
    RecordingOperationObserver,
]:
    state = _LeaseState(
        PlaywrightLease(
            playwright=object.__new__(Playwright),
            browser=object.__new__(Browser),
            mode=PlaywrightMode.LOCAL,
        )
    )

    async def create() -> PlaywrightLease:
        return state.lease

    async def close_lease(lease: PlaywrightLease) -> None:
        try:
            await close(lease)
        finally:
            state.alive = False

    observer = RecordingOperationObserver()
    leases = ExecutionLeaseProvider(
        create=create,
        is_alive=lambda _: state.alive,
        close=close_lease,
        observer=observer,
        translate=_translate,
        observation_attributes={"render.backend": "playwright"},
    )
    capability = PlaywrightAccessAdapter(leases, observer)
    return capability, state, leases, observer


async def test_page_context_holds_runtime_lease_until_page_closes(
    mocker: MockerFixture,
) -> None:
    order: list[str] = []

    async def close(lease: PlaywrightLease) -> None:
        del lease
        order.append("runtime-close")

    capability, _, leases, observer = _capability(close=close)
    page = object.__new__(Page)

    @asynccontextmanager
    async def open_page_context(
        _context: object,
        **kwargs: object,
    ) -> AsyncIterator[Page]:
        assert kwargs == {}
        try:
            yield page
        finally:
            order.append("page-close")

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright._page.PageContext.open",
        open_page_context,
    )
    async with anyio.create_task_group() as task_group, capability.page() as opened:
        assert opened is page
        task_group.start_soon(leases.aclose)
        await checkpoint()
        assert order == []

    assert order == ["page-close", "runtime-close"]
    assert (
        "playwright.native.page",
        {"render.backend": "playwright", "render.access": "native"},
        "success",
    ) in observer.operations


async def test_browser_context_yields_native_instance_and_tracks_lease() -> None:
    async def close(lease: PlaywrightLease) -> None:
        del lease

    capability, state, leases, observer = _capability(close=close)

    async with anyio.create_task_group() as task_group, capability.browser() as browser:
        assert browser is state.lease.browser
        task_group.start_soon(leases.aclose)
        await checkpoint()
        assert state.alive is True

    assert state.alive is False
    assert (
        "playwright.native.browser",
        {"render.backend": "playwright", "render.access": "native"},
        "success",
    ) in observer.operations
