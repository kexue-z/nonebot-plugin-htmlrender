"""Shared lease-based lifecycle over the legacy backend runtimes.

Interim machinery: it wraps the legacy ``Backend`` runtime/session objects
behind the ``ApplicationLifecycle`` and ``PreparedHtmlExecutor`` ports until
the physical adapter migration absorbs the backend modules. Application code
never sees runtime or session handles; executors acquire leases themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import anyio
from nonebot.log import logger

from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderExecutionError,
    ProviderLifecycleError,
)
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from contextlib import AbstractContextManager

    from nonebot_plugin_htmlrender.adapters._backend import (
        Backend,
        RenderRuntime,
        RenderSession,
    )
    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )
    from nonebot_plugin_htmlrender.rendering.errors import RenderingError
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy

    TranslateFactory = Callable[
        [str, type[RenderingError]],
        AbstractContextManager[None],
    ]
    ProbeFn = Callable[[RenderSession], Awaitable[None]]
    RasterizeFn = Callable[
        [RenderSession, PreparedHtml, RasterOptions, "ResourcePolicy | None"],
        Awaitable[bytes],
    ]

_TEARDOWN_TIMEOUT_SECONDS = 30.0


@final
class LeasedBackendLifecycle:
    """Owns the runtime/session pair and rebuilds it when the engine dies."""

    def __init__(
        self,
        *,
        backend: Backend,
        observer: OperationObserver,
        translate: TranslateFactory,
        observation_attributes: Mapping[str, str],
        probe: ProbeFn | None = None,
    ) -> None:
        self._backend = backend
        self._observer = observer
        self._translate = translate
        self._attributes = dict(observation_attributes)
        self._probe_fn = probe
        self._runtime: RenderRuntime | None = None
        self._session: RenderSession | None = None
        self._lock = anyio.Lock()

    def _attrs(self, **extra: str) -> dict[str, str]:
        return {**self._attributes, **extra}

    def _session_alive(self, session: RenderSession | None) -> bool:
        if session is None:
            return False
        try:
            return self._backend.is_alive(session)
        except Exception:
            return False

    async def lease(self) -> RenderSession:
        """Return a live session, lazily (re)building the runtime."""
        session = self._session
        if session is not None and self._session_alive(session):
            with observe_operation(
                self._observer,
                "render.get_render",
                self._attrs(**{"render.cache_hit": "true"}),
            ):
                return session
        async with self._lock:
            session = self._session
            if session is not None and self._session_alive(session):
                with observe_operation(
                    self._observer,
                    "render.get_render",
                    self._attrs(**{"render.cache_hit": "true"}),
                ):
                    return session
            with observe_operation(
                self._observer,
                "render.get_render",
                self._attrs(**{"render.cache_hit": "false"}),
            ):
                return await self._restart_locked()

    async def _restart_locked(self) -> RenderSession:
        await self._teardown_locked()
        with (
            observe_operation(self._observer, "render.startup", self._attrs()),
            self._translate("startup", ProviderLifecycleError),
        ):
            for step in self._backend.startup_steps():
                await step()
            runtime = await self._backend.create_runtime()
            try:
                session = await self._backend.create_session(runtime)
            except BaseException:
                await self._close_handle(runtime)
                raise
        self._runtime = runtime
        self._session = session
        return session

    async def startup(self) -> None:
        async with self._lock:
            if self._session_alive(self._session):
                return
            await self._restart_locked()

    async def probe(self) -> None:
        session = await self.lease()
        if self._probe_fn is None:
            return
        with self._translate("probe", ProviderLifecycleError):
            await self._probe_fn(session)

    async def aclose(self) -> None:
        async with self._lock:
            session = self._session
            runtime = self._runtime
            self._session = None
            self._runtime = None
            if session is None and runtime is None:
                return
            with observe_operation(
                self._observer,
                "render.shutdown",
                self._attrs(),
            ):
                await self._close_handle(session)
                await self._close_handle(runtime)

    async def _teardown_locked(self) -> None:
        session = self._session
        runtime = self._runtime
        self._session = None
        self._runtime = None
        await self._close_handle(session)
        await self._close_handle(runtime)

    async def _close_handle(
        self,
        handle: RenderRuntime | RenderSession | None,
    ) -> None:
        if handle is None:
            return
        with anyio.CancelScope(shield=True):
            try:
                with anyio.move_on_after(_TEARDOWN_TIMEOUT_SECONDS) as scope:
                    await handle.aclose()
            except Exception as error:
                logger.opt(colors=True).warning(
                    "<d>[htmlrender.adapters]</d> Error while closing render "
                    "resources: <r>{error}</r>.",
                    error=error,
                )
                return
            if scope.cancel_called:
                logger.opt(colors=True).warning(
                    "<d>[htmlrender.adapters]</d> Closing render resources "
                    "exceeded the bounded wait of {timeout}s; continuing.",
                    timeout=_TEARDOWN_TIMEOUT_SECONDS,
                )


@final
class LeasedPreparedHtmlExecutor:
    """Executes prepared documents against a leased backend session."""

    def __init__(
        self,
        *,
        lifecycle: LeasedBackendLifecycle,
        rasterize: RasterizeFn,
        translate: TranslateFactory,
        observer: OperationObserver,
        operation: str | None,
        observation_attributes: Mapping[str, str],
    ) -> None:
        self._lifecycle = lifecycle
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
    ) -> bytes:
        session = await self._lifecycle.lease()
        if self._operation is None:
            return await self._run(
                session,
                prepared,
                options,
                resource_policy,
                timeout_seconds,
            )
        with observe_operation(
            self._observer,
            self._operation,
            dict(self._attributes),
        ):
            return await self._run(
                session,
                prepared,
                options,
                resource_policy,
                timeout_seconds,
            )

    async def _run(
        self,
        session: RenderSession,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
        timeout_seconds: float | None,
    ) -> bytes:
        operation = self._operation or "render"
        with self._translate(operation, ProviderExecutionError):
            if timeout_seconds is None:
                return await self._rasterize(
                    session,
                    prepared,
                    options,
                    resource_policy,
                )
            try:
                with anyio.fail_after(timeout_seconds):
                    return await self._rasterize(
                        session,
                        prepared,
                        options,
                        resource_policy,
                    )
            except TimeoutError as error:
                raise ProviderExecutionError(
                    f"Render operation timed out after {timeout_seconds} seconds."
                ) from error


__all__ = ["LeasedBackendLifecycle", "LeasedPreparedHtmlExecutor"]
