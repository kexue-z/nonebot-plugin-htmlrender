from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import anyio
from anyio.lowlevel import checkpoint
import pytest

from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PlaywrightCapabilityAdapter,
)
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderLifecycleError,
    RenderingError,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopOperationObserver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from playwright.async_api import Page
    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease


@dataclass(slots=True)
class _Lease:
    alive: bool = True


@contextmanager
def _translate(
    operation: str,
    error_type: type[RenderingError],
) -> Iterator[None]:
    try:
        yield
    except Exception as error:
        raise error_type(f"{operation}: {error}") from error


def _capability(
    *,
    close: Callable[[_Lease], Awaitable[None]],
) -> tuple[
    PlaywrightCapabilityAdapter,
    _Lease,
    ExecutionLeaseProvider[_Lease],
]:
    lease = _Lease()

    async def create() -> _Lease:
        return lease

    observer = NoopOperationObserver()
    leases = ExecutionLeaseProvider(
        create=create,
        is_alive=lambda value: value.alive,
        close=close,
        observer=observer,
        translate=_translate,
        observation_attributes={"render.backend": "playwright"},
    )
    capability = PlaywrightCapabilityAdapter(
        cast("ExecutionLeaseProvider[PlaywrightLease]", leases),
        observer,
    )
    return capability, lease, leases


async def test_page_context_holds_runtime_lease_until_page_closes(
    mocker: MockerFixture,
) -> None:
    order: list[str] = []

    async def close(lease: _Lease) -> None:
        lease.alive = False
        order.append("runtime-close")

    capability, _, leases = _capability(close=close)
    page = cast("Page", object())

    @asynccontextmanager
    async def open_page_context(**kwargs: object) -> AsyncIterator[Page]:
        assert "lease" in kwargs
        try:
            yield page
        finally:
            order.append("page-close")

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright._page.open_page_context",
        open_page_context,
    )
    async with anyio.create_task_group() as task_group, capability.page() as opened:
        assert opened is page
        task_group.start_soon(leases.aclose)
        await checkpoint()
        assert order == []

    assert order == ["page-close", "runtime-close"]


async def test_capture_holds_runtime_lease_and_rejects_after_close(
    mocker: MockerFixture,
) -> None:
    capture_entered = anyio.Event()
    release_capture = anyio.Event()
    closed: list[_Lease] = []

    async def close(lease: _Lease) -> None:
        lease.alive = False
        closed.append(lease)

    capability, lease, leases = _capability(close=close)

    async def capture_html_element(
        url: str,
        element: str,
        **kwargs: object,
    ) -> bytes:
        assert (url, element) == ("https://example.test", "#target")
        assert kwargs["lease"] is lease
        capture_entered.set()
        await release_capture.wait()
        return b"image"

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.capture_html_element",
        capture_html_element,
    )
    results: list[bytes] = []

    async def capture() -> None:
        results.append(
            await capability.capture_element(
                "https://example.test",
                "#target",
            )
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(capture)
        await capture_entered.wait()
        task_group.start_soon(leases.aclose)
        await checkpoint()
        assert closed == []
        release_capture.set()

    assert results == [b"image"]
    assert closed == [lease]
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await capability.capture_element("https://example.test", "#target")
