"""Application aggregate: renderer, capability catalog, and lifecycle."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, final

import anyio

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderLifecycleError,
    RenderingError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
    from nonebot_plugin_htmlrender.rendering.ports import ApplicationLifecycle
    from nonebot_plugin_htmlrender.resources.service import ResourceService

    from .facades import ApplicationResources
    from .renderer import Renderer

from .extensions import ApplicationExtensions
from .facades import AdmittedHtmlPreparer, AdmittedResourceService


class _AppState(Enum):
    NEW = auto()
    STARTED = auto()
    CLOSING = auto()
    CLOSED = auto()


@final
class Application:
    """Process-facing aggregate composed once at the composition root."""

    def __init__(
        self,
        *,
        renderer: Renderer,
        preparation: HtmlPreparer,
        resources: ResourceService,
        lifecycle: ApplicationLifecycle,
        operation_admission: OperationAdmissionGate,
        extensions: CapabilityCatalog | None = None,
    ) -> None:
        self._renderer = renderer
        self._operation_admission = operation_admission
        self._preparation = AdmittedHtmlPreparer(preparation, self._operation_admission)
        self._resources = AdmittedResourceService(resources, self._operation_admission)
        self._lifecycle = lifecycle
        catalog = extensions if extensions is not None else CapabilityCatalog()
        self._extensions = ApplicationExtensions(catalog)
        self._state = _AppState.NEW
        self._lock = anyio.Lock()

    @property
    def renderer(self) -> Renderer:
        return self._renderer

    @property
    def preparation(self) -> HtmlPreparer:
        return self._preparation

    @property
    def resources(self) -> ApplicationResources:
        return self._resources

    @property
    def extensions(self) -> ApplicationExtensions:
        return self._extensions

    async def _run_lifecycle(
        self,
        operation: str,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await callback()
        except RenderingError:
            raise
        except Exception as error:
            raise ProviderLifecycleError(
                f"Application lifecycle {operation} failed.",
                source=error,
            ) from error

    async def startup(self) -> None:
        """Start the provider runtime; idempotent and concurrency-safe."""
        async with self._lock:
            if self._state in {_AppState.CLOSING, _AppState.CLOSED}:
                raise ProviderLifecycleError(
                    "Application is closing or closed; build a new composition "
                    "to render again."
                )
            if self._state is _AppState.STARTED:
                return
            await self._run_lifecycle("startup", self._lifecycle.startup)
            self._state = _AppState.STARTED

    async def probe(self) -> None:
        """Run the provider-defined minimal probe."""
        await self.startup()
        async with self._lock:
            if self._state is not _AppState.STARTED:
                raise ProviderLifecycleError(
                    "Application is closing or closed; build a new composition "
                    "to probe again."
                )
            await self._run_lifecycle("probe", self._lifecycle.probe)

    async def aclose(self) -> None:
        """Close the provider runtime; idempotent for multiple callers."""
        async with self._lock:
            if self._state is _AppState.CLOSED:
                return
            # A failed teardown remains retryable, but startup is permanently
            # rejected once closing has begun.
            self._state = _AppState.CLOSING
            await self._operation_admission.stop_accepting_and_drain()
            await self._run_lifecycle("aclose", self._lifecycle.aclose)
            self._state = _AppState.CLOSED
