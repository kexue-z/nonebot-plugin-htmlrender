"""Typed Takumi capability resolved at the API/composition boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiAPIAdapter
from nonebot_plugin_htmlrender.adapters.takumi.runtime import require_runtime_state
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from takumi_py import Renderer

    from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
    from nonebot_plugin_htmlrender.adapters.takumi.runtime import TakumiRuntimeState
    from nonebot_plugin_htmlrender.capabilities.takumi import TakumiAPI
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver

_OBSERVATION_ATTRIBUTES = {
    "render.backend": "takumi",
    "render.access": "native",
}


@final
class TakumiAccessAdapter:
    """Lease the managed Takumi API or the provider-owned Renderer.

    ``api()`` leases the live runtime for the lifetime of its async context
    and yields the typed adapter bound to it. ``renderer()`` yields
    the upstream object itself for explicitly unmanaged native operations.
    """

    def __init__(
        self,
        leases: ExecutionLeaseProvider[TakumiRuntimeState],
        observer: OperationObserver,
    ) -> None:
        self._leases = leases
        self._observer = observer

    @asynccontextmanager
    async def api(self) -> AsyncIterator[TakumiAPI]:
        async with self._leases.lease() as state:
            yield TakumiAPIAdapter(require_runtime_state(state), self._observer)

    @asynccontextmanager
    async def renderer(self) -> AsyncIterator[Renderer]:
        """Lease the provider-owned native renderer without proxying it."""
        with observe_operation(
            self._observer,
            "takumi.native.renderer",
            _OBSERVATION_ATTRIBUTES,
        ):
            async with self._leases.lease() as state:
                runtime = require_runtime_state(state)
                renderer = runtime.renderer
                if renderer is None:
                    raise RuntimeError("Takumi runtime does not expose a Renderer.")
                yield renderer


__all__ = ["TakumiAccessAdapter"]
