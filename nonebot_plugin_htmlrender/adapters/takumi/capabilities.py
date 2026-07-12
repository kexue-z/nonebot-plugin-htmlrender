"""Typed Takumi capability resolved at the API/composition boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiExtension
from nonebot_plugin_htmlrender.adapters.takumi.runtime import require_runtime_state
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nonebot_plugin_htmlrender.adapters._lease import ExecutionLeaseProvider
    from nonebot_plugin_htmlrender.adapters.takumi.runtime import TakumiRuntimeState
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver


@final
class TakumiCapabilities:
    """Native Takumi surface: node, style, animation, font, compile/measure.

    ``extension()`` leases the live runtime for the lifetime of its async
    context and yields the typed native extension bound to it.
    """

    def __init__(
        self,
        leases: ExecutionLeaseProvider[TakumiRuntimeState],
        observer: OperationObserver,
    ) -> None:
        self._leases = leases
        self._observer = observer

    @asynccontextmanager
    async def extension(self) -> AsyncIterator[TakumiExtension]:
        async with self._leases.lease() as state:
            yield TakumiExtension(require_runtime_state(state), self._observer)


TAKUMI_CAPABILITIES: CapabilityKey[TakumiCapabilities] = CapabilityKey(
    "takumi.capabilities",
    TakumiCapabilities,
)

__all__ = ["TAKUMI_CAPABILITIES", "TakumiCapabilities"]
