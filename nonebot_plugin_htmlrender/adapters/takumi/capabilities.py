"""Typed Takumi capability resolved at the API/composition boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiExtension
from nonebot_plugin_htmlrender.adapters.takumi.runtime import require_runtime_state
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.adapters._lease import LeasedBackendLifecycle


@final
class TakumiCapabilities:
    """Native Takumi surface: node, style, animation, font, compile/measure.

    ``extension()`` leases the live runtime and returns the typed native
    extension bound to it; callers must not cache the returned object across
    runtime rebuilds.
    """

    def __init__(self, lifecycle: LeasedBackendLifecycle) -> None:
        self._lifecycle = lifecycle

    async def extension(self) -> TakumiExtension:
        session = await self._lifecycle.lease()
        return TakumiExtension(require_runtime_state(session.handle))


TAKUMI_CAPABILITIES: CapabilityKey[TakumiCapabilities] = CapabilityKey(
    "takumi.capabilities",
    TakumiCapabilities,
)

__all__ = ["TAKUMI_CAPABILITIES", "TakumiCapabilities"]
