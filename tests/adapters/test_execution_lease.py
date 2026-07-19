from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from anyio.lowlevel import checkpoint
import pytest

from nonebot_plugin_htmlrender.adapters import _lease as lease_module
from nonebot_plugin_htmlrender.adapters._lease import (
    ExecutionLeaseProvider,
    PreparedHtmlLeaseExecutor,
)
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderExecutionError,
    ProviderLifecycleError,
    RenderingError,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopOperationObserver
from tests.image_fixtures import rendered_image

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nonebot_plugin_htmlrender.rendering import RenderedImage
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy


@dataclass(slots=True)
class _Lease:
    generation: int
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


def _provider(
    create,
    close,
) -> ExecutionLeaseProvider[_Lease]:
    return ExecutionLeaseProvider(
        create=create,
        is_alive=lambda lease: lease.alive,
        close=close,
        observer=NoopOperationObserver(),
        translate=_translate,
        observation_attributes={"render.backend": "test"},
    )


async def test_concurrent_cold_leases_share_one_creation() -> None:
    created: list[_Lease] = []
    results: list[_Lease] = []

    async def create() -> _Lease:
        await anyio.sleep(0.01)
        lease = _Lease(len(created) + 1)
        created.append(lease)
        return lease

    async def close(lease: _Lease) -> None:
        lease.alive = False

    provider = _provider(create, close)

    async def acquire() -> None:
        async with provider.lease() as lease:
            results.append(lease)

    async with anyio.create_task_group() as task_group:
        for _ in range(5):
            task_group.start_soon(acquire)

    assert len(created) == 1
    assert results == [created[0]] * 5


async def test_dead_lease_is_closed_before_single_rebuild() -> None:
    created: list[_Lease] = []
    closed: list[_Lease] = []

    async def create() -> _Lease:
        lease = _Lease(len(created) + 1)
        created.append(lease)
        return lease

    async def close(lease: _Lease) -> None:
        lease.alive = False
        closed.append(lease)

    provider = _provider(create, close)
    async with provider.lease() as first:
        pass
    first.alive = False

    async with provider.lease() as second:
        pass

    assert second.generation == 2
    assert closed == [first]


async def test_failed_creation_is_translated_and_retryable() -> None:
    attempts = 0

    async def create() -> _Lease:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("engine failed")
        return _Lease(attempts)

    async def close(lease: _Lease) -> None:
        lease.alive = False

    provider = _provider(create, close)

    with pytest.raises(ProviderLifecycleError, match="engine failed"):
        await provider.startup()
    async with provider.lease() as lease:
        assert lease.generation == 2


async def test_close_is_idempotent_and_shielded_from_caller_cancellation() -> None:
    closed: list[_Lease] = []

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        await checkpoint()
        lease.alive = False
        closed.append(lease)

    provider = _provider(create, close)
    async with provider.lease() as lease:
        pass

    with anyio.CancelScope() as scope:
        scope.cancel()
        await provider.aclose()
    await provider.aclose()

    assert closed == [lease]


async def test_close_rejects_new_work_and_drains_the_active_operation() -> None:
    close_order: list[str] = []
    operation_entered = anyio.Event()
    release_operation = anyio.Event()

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        close_order.append("close")
        lease.alive = False

    async def probe(lease: _Lease) -> None:
        close_order.append(f"probe-{lease.generation}")

    provider = ExecutionLeaseProvider(
        create=create,
        is_alive=lambda lease: lease.alive,
        close=close,
        observer=NoopOperationObserver(),
        translate=_translate,
        observation_attributes={"render.backend": "test"},
        probe=probe,
    )

    async def operate() -> None:
        async with provider.lease():
            operation_entered.set()
            await release_operation.wait()
            close_order.append("operation")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(operate)
        await operation_entered.wait()
        task_group.start_soon(provider.aclose)
        await checkpoint()

        with pytest.raises(ProviderLifecycleError, match="closing or closed"):
            async with provider.lease():
                pass
        with pytest.raises(ProviderLifecycleError, match="closing or closed"):
            await provider.startup()
        with pytest.raises(ProviderLifecycleError, match="closing or closed"):
            await provider.probe()

        assert close_order == []
        release_operation.set()

    assert close_order == ["operation", "close"]
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        async with provider.lease():
            pass
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await provider.startup()
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await provider.probe()


async def test_drain_timeout_keeps_runtime_and_close_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lease_module, "_DRAIN_TIMEOUT_SECONDS", 0.01)
    closed: list[_Lease] = []
    operation_entered = anyio.Event()
    release_operation = anyio.Event()

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        lease.alive = False
        closed.append(lease)

    provider = _provider(create, close)

    async def operate() -> None:
        async with provider.lease():
            operation_entered.set()
            await release_operation.wait()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(operate)
        await operation_entered.wait()
        with pytest.raises(ProviderLifecycleError, match="did not drain"):
            await provider.aclose()
        # The runtime must survive a drain timeout; only admission stops.
        assert closed == []
        with pytest.raises(ProviderLifecycleError, match="close failed"):
            async with provider.lease():
                pass
        release_operation.set()

    await provider.aclose()
    assert len(closed) == 1


async def test_close_failure_keeps_owner_and_retried_close_succeeds() -> None:
    close_calls = 0

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("teardown exploded")
        lease.alive = False

    provider = _provider(create, close)
    async with provider.lease():
        pass

    with pytest.raises(ProviderLifecycleError, match="teardown exploded"):
        await provider.aclose()
    with pytest.raises(ProviderLifecycleError, match="close failed"):
        async with provider.lease():
            pass

    await provider.aclose()
    assert close_calls == 2
    await provider.aclose()
    assert close_calls == 2


async def test_close_timeout_is_reported_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lease_module, "_TEARDOWN_TIMEOUT_SECONDS", 0.01)
    close_calls = 0

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            await anyio.sleep_forever()
        lease.alive = False

    provider = _provider(create, close)
    async with provider.lease():
        pass

    with pytest.raises(ProviderLifecycleError, match="bounded wait"):
        await provider.aclose()
    await provider.aclose()
    assert close_calls == 2


async def test_stale_rebuild_close_failure_poisons_until_close_retry() -> None:
    created: list[_Lease] = []
    close_calls = 0

    async def create() -> _Lease:
        lease = _Lease(len(created) + 1)
        created.append(lease)
        return lease

    async def close(lease: _Lease) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("old runtime is stuck")
        lease.alive = False

    provider = _provider(create, close)
    async with provider.lease() as first:
        pass
    first.alive = False

    with pytest.raises(ProviderLifecycleError, match="old runtime is stuck"):
        async with provider.lease():
            pass
    # No second runtime may be stacked on an unconfirmed teardown.
    assert len(created) == 1
    with pytest.raises(ProviderLifecycleError, match="close failed"):
        async with provider.lease():
            pass

    await provider.aclose()
    assert close_calls == 2


async def test_concurrent_close_calls_share_one_close_attempt() -> None:
    close_calls = 0
    close_entered = anyio.Event()
    release_close = anyio.Event()

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        nonlocal close_calls
        close_calls += 1
        close_entered.set()
        await release_close.wait()
        lease.alive = False

    provider = _provider(create, close)
    async with provider.lease():
        pass

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(provider.aclose)
        await close_entered.wait()
        task_group.start_soon(provider.aclose)
        await checkpoint()
        release_close.set()

    assert close_calls == 1


async def test_runtime_created_after_close_is_disposed_without_reopening() -> None:
    create_entered = anyio.Event()
    finish_create = anyio.Event()
    created: list[_Lease] = []
    closed: list[_Lease] = []
    errors: list[ProviderLifecycleError] = []

    async def create() -> _Lease:
        create_entered.set()
        await finish_create.wait()
        lease = _Lease(1)
        created.append(lease)
        return lease

    async def close(lease: _Lease) -> None:
        lease.alive = False
        closed.append(lease)

    provider = _provider(create, close)

    async def acquire() -> None:
        try:
            async with provider.lease():
                pytest.fail("A lease created after close must not be admitted")
        except ProviderLifecycleError as error:
            errors.append(error)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(acquire)
        await create_entered.wait()
        await provider.aclose()
        finish_create.set()

    assert closed == created
    assert len(errors) == 1
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        async with provider.lease():
            pass


async def test_prepared_executor_holds_lease_until_rasterize_finishes() -> None:
    rasterize_entered = anyio.Event()
    release_rasterize = anyio.Event()
    closed: list[_Lease] = []
    results: list[RenderedImage] = []
    expected = rendered_image("png", width=128, height=64)

    async def create() -> _Lease:
        return _Lease(1)

    async def close(lease: _Lease) -> None:
        lease.alive = False
        closed.append(lease)

    async def rasterize(
        lease: _Lease,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
    ) -> RenderedImage:
        del prepared, options, resource_policy
        assert lease.alive is True
        rasterize_entered.set()
        await release_rasterize.wait()
        return expected

    provider = _provider(create, close)
    executor = PreparedHtmlLeaseExecutor(
        leases=provider,
        rasterize=rasterize,
        translate=_translate,
        observer=NoopOperationObserver(),
        operation=None,
        observation_attributes={"render.backend": "test"},
    )

    async def execute() -> None:
        results.append(
            await executor.execute(
                prepare_html("<p>test</p>"),
                RasterOptions(width=64, height=32),
            )
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(execute)
        await rasterize_entered.wait()
        task_group.start_soon(provider.aclose)
        await checkpoint()
        assert closed == []
        release_rasterize.set()

    assert results == [expected]
    assert len(closed) == 1
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await executor.execute(
            prepare_html("<p>closed</p>"),
            RasterOptions(width=64, height=32),
        )


async def test_prepared_executor_timeout_includes_lazy_lease_startup() -> None:
    async def create() -> _Lease:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def close(lease: _Lease) -> None:
        lease.alive = False

    async def rasterize(
        lease: _Lease,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
    ) -> RenderedImage:
        del lease, prepared, options, resource_policy
        return rendered_image("png", width=128, height=64)

    executor = PreparedHtmlLeaseExecutor(
        leases=_provider(create, close),
        rasterize=rasterize,
        translate=_translate,
        observer=NoopOperationObserver(),
        operation=None,
        observation_attributes={"render.backend": "test"},
    )

    with pytest.raises(ProviderExecutionError, match="timed out"):
        await executor.execute(
            prepare_html("<p>test</p>"),
            RasterOptions(width=64, height=32),
            timeout_seconds=0.01,
        )
