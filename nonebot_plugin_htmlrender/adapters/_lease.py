"""Typed lease lifecycle shared by engine adapters.

The lifecycle owns one provider-local lease value.  Concrete adapters decide
what that value contains and how it is created, checked, probed, and closed;
the shared machinery only supplies lazy construction, singleflight rebuilds,
bounded teardown, observation, and stable error translation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING, Generic, TypeVar, final

import anyio

from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderExecutionError,
    ProviderLifecycleError,
)
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
    from contextlib import AbstractContextManager

    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )
    from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
    from nonebot_plugin_htmlrender.rendering.errors import RenderingError
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy

LeaseT = TypeVar("LeaseT")

if TYPE_CHECKING:
    TranslateFactory = Callable[
        [str, type[RenderingError]],
        AbstractContextManager[None],
    ]
    CreateLeaseFn = Callable[[], Awaitable[LeaseT]]
    LeaseAliveFn = Callable[[LeaseT], bool]
    CloseLeaseFn = Callable[[LeaseT], Awaitable[None]]
    ProbeLeaseFn = Callable[[LeaseT], Awaitable[None]]
    RasterizeLeaseFn = Callable[
        [LeaseT, PreparedHtml, RasterOptions, "ResourcePolicy | None"],
        Awaitable[RenderedImage],
    ]

_TEARDOWN_TIMEOUT_SECONDS = 30.0
_DRAIN_TIMEOUT_SECONDS = 30.0


class _LeaseProviderState(Enum):
    OPEN = auto()
    CLOSING = auto()
    CLOSED = auto()
    CLOSE_FAILED = auto()


@final
class ExecutionLeaseProvider(Generic[LeaseT]):
    """Lazily own one runtime and lease it to bounded operations."""

    def __init__(
        self,
        *,
        create: CreateLeaseFn[LeaseT],
        is_alive: LeaseAliveFn[LeaseT],
        close: CloseLeaseFn[LeaseT],
        observer: OperationObserver,
        translate: TranslateFactory,
        observation_attributes: Mapping[str, str],
        probe: ProbeLeaseFn[LeaseT] | None = None,
    ) -> None:
        self._create = create
        self._is_alive = is_alive
        self._close = close
        self._observer = observer
        self._translate = translate
        self._attributes = dict(observation_attributes)
        self._probe_fn = probe
        self._lease: LeaseT | None = None
        self._lock = anyio.Lock()
        self._state = _LeaseProviderState.OPEN
        self._active_operations = 0
        self._drained = anyio.Event()
        self._drained.set()
        self._closed = anyio.Event()
        self._close_error: BaseException | None = None

    def _attrs(self, **extra: str) -> dict[str, str]:
        return {**self._attributes, **extra}

    def _lease_alive(self, lease: LeaseT | None) -> bool:
        if lease is None:
            return False
        try:
            return self._is_alive(lease)
        except Exception:
            return False

    def _ensure_open(self) -> None:
        if self._state is _LeaseProviderState.CLOSE_FAILED:
            raise ProviderLifecycleError(
                "Execution lease provider close failed; the runtime is "
                "retained and only a retried aclose() may release it.",
                source=self._close_error,
            ) from self._close_error
        if self._state is not _LeaseProviderState.OPEN:
            raise ProviderLifecycleError(
                "Execution lease provider is closing or closed; build a new "
                "composition to render again."
            )

    def _begin_operation(self) -> None:
        self._ensure_open()
        if self._active_operations == 0:
            self._drained = anyio.Event()
        self._active_operations += 1

    def _end_operation(self) -> None:
        self._active_operations -= 1
        if self._active_operations == 0:
            self._drained.set()

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[LeaseT]:
        """Lease a live runtime for the complete duration of one operation."""
        lease = await self._acquire()
        try:
            yield lease
        finally:
            self._end_operation()

    async def _acquire(self) -> LeaseT:
        self._ensure_open()
        await self._lock.acquire()
        try:
            self._ensure_open()
            lease = self._lease
            if lease is not None and self._lease_alive(lease):
                with observe_operation(
                    self._observer,
                    "render.get_render",
                    self._attrs(**{"render.cache_hit": "true"}),
                ):
                    self._begin_operation()
                    return lease
            with observe_operation(
                self._observer,
                "render.get_render",
                self._attrs(**{"render.cache_hit": "false"}),
            ):
                lease = await self._restart_locked()
            self._begin_operation()
            return lease
        finally:
            self._lock.release()

    async def _restart_locked(self) -> LeaseT:
        if self._lease is not None and self._active_operations > 0:
            drained = self._drained
            await drained.wait()
            self._ensure_open()
        await self._teardown_locked()
        self._ensure_open()
        with (
            observe_operation(self._observer, "render.startup", self._attrs()),
            self._translate("startup", ProviderLifecycleError),
        ):
            lease = await self._create()
        if self._state is not _LeaseProviderState.OPEN:
            await self._close_lease(lease)
            self._ensure_open()
        self._lease = lease
        return lease

    async def startup(self) -> None:
        self._ensure_open()
        await self._lock.acquire()
        try:
            self._ensure_open()
            if self._lease_alive(self._lease):
                return
            await self._restart_locked()
        finally:
            self._lock.release()

    async def probe(self) -> None:
        async with self.lease() as lease:
            if self._probe_fn is None:
                return
            with self._translate("probe", ProviderLifecycleError):
                await self._probe_fn(lease)

    async def aclose(self) -> None:
        """Close the owned runtime; failures keep the owner and stay retryable.

        Concurrent calls share one close attempt's outcome. A drain timeout
        or a teardown failure moves the provider to ``CLOSE_FAILED``: the
        lease is retained, new work is rejected, and only a later
        ``aclose()`` retries the release. ``CLOSED`` is entered exclusively
        after the underlying close confirmed completion.
        """
        with anyio.CancelScope(shield=True):
            if self._state is _LeaseProviderState.CLOSED:
                return
            if self._state is _LeaseProviderState.CLOSING:
                await self._closed.wait()
                if self._state is _LeaseProviderState.CLOSED:
                    return
                raise ProviderLifecycleError(
                    "The shared close attempt failed; retry aclose().",
                    source=self._close_error,
                ) from self._close_error

            self._state = _LeaseProviderState.CLOSING
            self._closed = anyio.Event()
            try:
                if self._active_operations > 0:
                    with anyio.move_on_after(_DRAIN_TIMEOUT_SECONDS) as scope:
                        await self._drained.wait()
                    if scope.cancel_called:
                        raise ProviderLifecycleError(
                            "Render operations did not drain within the "
                            f"bounded wait of {_DRAIN_TIMEOUT_SECONDS}s; the "
                            "runtime is retained and close may be retried."
                        )
                lease = self._lease
                if lease is not None:
                    with observe_operation(
                        self._observer,
                        "render.shutdown",
                        self._attrs(),
                    ):
                        await self._close_lease(lease)
                    self._lease = None
                self._state = _LeaseProviderState.CLOSED
                self._close_error = None
            except BaseException as error:
                self._state = _LeaseProviderState.CLOSE_FAILED
                self._close_error = error
                raise
            finally:
                self._closed.set()

    async def _teardown_locked(self) -> None:
        lease = self._lease
        if lease is None:
            return
        try:
            await self._close_lease(lease)
        except BaseException as error:
            # A stale rebuild must not stack a second runtime on top of an
            # unconfirmed teardown; only a retried aclose() may recover.
            self._state = _LeaseProviderState.CLOSE_FAILED
            self._close_error = error
            raise
        self._lease = None

    async def _close_lease(self, lease: LeaseT) -> None:
        with anyio.CancelScope(shield=True):
            try:
                with anyio.fail_after(_TEARDOWN_TIMEOUT_SECONDS):
                    await self._close(lease)
            except TimeoutError as error:
                raise ProviderLifecycleError(
                    "Closing the render runtime exceeded the bounded wait of "
                    f"{_TEARDOWN_TIMEOUT_SECONDS}s; the lease is retained for "
                    "a retried close.",
                    source=error,
                ) from error
            except ProviderLifecycleError:
                raise
            except Exception as error:
                raise ProviderLifecycleError(
                    "Closing the render runtime failed.",
                    source=error,
                ) from error


@final
class PreparedHtmlLeaseExecutor(Generic[LeaseT]):
    """Execute prepared documents against a provider-local typed lease."""

    def __init__(
        self,
        *,
        leases: ExecutionLeaseProvider[LeaseT],
        rasterize: RasterizeLeaseFn[LeaseT],
        translate: TranslateFactory,
        observer: OperationObserver,
        operation: str | None,
        observation_attributes: Mapping[str, str],
    ) -> None:
        self._leases = leases
        self._rasterize = rasterize
        self._translate = translate
        self._observer = observer
        self._operation = operation
        self._attributes = dict(observation_attributes)

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> RenderedImage:
        if timeout_seconds is None:
            return await self._execute(prepared, options, resource_policy)
        try:
            with anyio.fail_after(timeout_seconds):
                return await self._execute(prepared, options, resource_policy)
        except TimeoutError as error:
            raise ProviderExecutionError(
                f"Render operation timed out after {timeout_seconds} seconds.",
                source=error,
            ) from error

    async def _execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
    ) -> RenderedImage:
        async with self._leases.lease() as lease:
            if self._operation is None:
                return await self._run(
                    lease,
                    prepared,
                    options,
                    resource_policy,
                )
            with observe_operation(
                self._observer,
                self._operation,
                dict(self._attributes),
            ):
                return await self._run(
                    lease,
                    prepared,
                    options,
                    resource_policy,
                )

    async def _run(
        self,
        lease: LeaseT,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
    ) -> RenderedImage:
        operation = self._operation or "render"
        with self._translate(operation, ProviderExecutionError):
            return await self._rasterize(
                lease,
                prepared,
                options,
                resource_policy,
            )


__all__ = ["ExecutionLeaseProvider", "PreparedHtmlLeaseExecutor"]
