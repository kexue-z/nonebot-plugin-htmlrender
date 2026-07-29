from __future__ import annotations

import anyio
import anyio.lowlevel
import pytest

from nonebot_plugin_htmlrender.rendering import (
    OperationAdmissionGate,
    ProviderLifecycleError,
)


async def test_cancelled_operation_still_releases_close_drain() -> None:
    gate = OperationAdmissionGate()
    operation_entered = anyio.Event()
    close_finished = anyio.Event()
    operation_scope: list[anyio.CancelScope] = []

    async def operation() -> None:
        with anyio.CancelScope() as scope:
            operation_scope.append(scope)
            async with gate.operation():
                operation_entered.set()
                await anyio.sleep_forever()

    async def close() -> None:
        await gate.stop_accepting_and_drain()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(operation)
        await operation_entered.wait()
        task_group.start_soon(close)
        await anyio.lowlevel.checkpoint()

        operation_scope[0].cancel()
        await close_finished.wait()

    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        async with gate.operation():
            pytest.fail("closed gate admitted an operation")


async def test_cancelled_close_transition_is_permanent_and_retryable() -> None:
    gate = OperationAdmissionGate()
    operation_entered = anyio.Event()
    release_operation = anyio.Event()
    cancelled_close_returned = anyio.Event()

    async def operation() -> None:
        async with gate.operation():
            operation_entered.set()
            await release_operation.wait()

    async def cancelled_close() -> None:
        with anyio.CancelScope() as scope:
            scope.cancel()
            await gate.stop_accepting_and_drain()
        cancelled_close_returned.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(operation)
        await operation_entered.wait()
        task_group.start_soon(cancelled_close)
        await cancelled_close_returned.wait()

        with pytest.raises(ProviderLifecycleError, match="closing or closed"):
            async with gate.operation():
                pytest.fail("closing gate admitted an operation")

        release_operation.set()
        await gate.stop_accepting_and_drain()
