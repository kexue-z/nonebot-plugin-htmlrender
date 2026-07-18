"""Stable public contract for Takumi-specific operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiExtension


@runtime_checkable
class TakumiCapability(Protocol):
    """Lease a typed Takumi extension bound to a live native runtime."""

    def extension(self) -> AbstractAsyncContextManager[TakumiExtension]: ...


TAKUMI_CAPABILITIES: CapabilityKey[TakumiCapability] = CapabilityKey(
    "takumi.capabilities",
    TakumiCapability,
)

__all__ = ["TAKUMI_CAPABILITIES", "TakumiCapability"]
