"""Application aggregate: renderer, capability catalog, and lifecycle."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, final

import anyio

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
from nonebot_plugin_htmlrender.rendering.errors import ProviderLifecycleError

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.rendering.ports import ApplicationLifecycle

    from .renderer import Renderer


class _AppState(Enum):
    NEW = auto()
    STARTED = auto()
    CLOSED = auto()


@final
class Application:
    """Process-facing aggregate composed once at the composition root."""

    def __init__(
        self,
        *,
        renderer: Renderer,
        lifecycle: ApplicationLifecycle,
        capabilities: CapabilityCatalog | None = None,
    ) -> None:
        self._renderer = renderer
        self._lifecycle = lifecycle
        self._capabilities = (
            capabilities if capabilities is not None else CapabilityCatalog()
        )
        self._state = _AppState.NEW
        self._lock = anyio.Lock()

    @property
    def renderer(self) -> Renderer:
        return self._renderer

    @property
    def capabilities(self) -> CapabilityCatalog:
        return self._capabilities

    async def startup(self) -> None:
        """Start the provider runtime; idempotent and concurrency-safe."""
        async with self._lock:
            if self._state is _AppState.CLOSED:
                raise ProviderLifecycleError(
                    "Application is closed; build a new composition to render again."
                )
            if self._state is _AppState.STARTED:
                return
            await self._lifecycle.startup()
            self._state = _AppState.STARTED

    async def probe(self) -> None:
        """Run the provider-defined minimal probe."""
        await self._lifecycle.probe()

    async def aclose(self) -> None:
        """Close the provider runtime; idempotent for multiple callers."""
        async with self._lock:
            if self._state is _AppState.CLOSED:
                return
            self._state = _AppState.CLOSED
            await self._lifecycle.aclose()
