"""Minimal render engine demonstrating the htmlrender provider SDK.

Configure it with::

    render:
      provider: echo
      provider_config:
        color: "#ff0000"

Every render command returns a fixed 1x1 PNG in the configured color;
useful for validating entry-point discovery, settings parsing, lifecycle,
and executor wiring without any native engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING, final
import zlib

from nonebot_plugin_htmlrender.providers import (
    EngineBindings,
    EngineId,
    PluginRequirement,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering import ProviderExecutionError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot_plugin_htmlrender.preparation import PreparedHtml, RasterOptions
    from nonebot_plugin_htmlrender.rendering import ResourcePolicy
    from nonebot_plugin_htmlrender.resources.config import ResourceConfig


@dataclass(frozen=True)
class EchoSettings:
    """Settings parsed from ``render.provider_config``."""

    color: str = "#000000"


def _parse_color(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"color must be #RRGGBB, got {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def _png_1x1(rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        raw = tag + payload
        return (
            struct.pack(">I", len(payload)) + raw + struct.pack(">I", zlib.crc32(raw))
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    scanline = zlib.compress(b"\x00" + bytes(rgb))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", scanline)
        + chunk(b"IEND", b"")
    )


@final
class _EchoLifecycle:
    async def startup(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@final
class _EchoExecutor:
    def __init__(self, settings: EchoSettings) -> None:
        self._payload = _png_1x1(_parse_color(settings.color))

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        del prepared, options, resource_policy, timeout_seconds
        return self._payload


@final
class EchoProvider:
    """A provider that always renders one constant pixel."""

    id: EngineId = "echo"

    def parse_settings(self, raw: Mapping[str, object]) -> object:
        color = raw.get("color", "#000000")
        if not isinstance(color, str):
            raise ValueError("provider_config.color must be a string")
        _parse_color(color)
        return EchoSettings(color=color)

    def availability(self, settings: object) -> ProviderAvailability:
        self._narrow(settings)
        return ProviderAvailability(available=True)

    def bootstrap_requirements(
        self,
        settings: object,
    ) -> tuple[PluginRequirement, ...]:
        self._narrow(settings)
        return ()

    def resource_configuration(
        self,
        settings: object,
        base: ResourceConfig,
    ) -> ResourceConfig:
        self._narrow(settings)
        return base

    def compose(
        self,
        settings: object,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        del dependencies
        parsed = self._narrow(settings)
        return EngineBindings(
            lifecycle=_EchoLifecycle(),
            prepared_html_executor=_EchoExecutor(parsed),
            description="Echo constant-pixel engine",
            observation_attributes={"render.backend": "echo"},
        )

    @staticmethod
    def _narrow(settings: object) -> EchoSettings:
        if not isinstance(settings, EchoSettings):
            raise ProviderExecutionError(
                "Echo provider received settings not produced by parse_settings()."
            )
        return settings


PROVIDER = EchoProvider()

__all__ = ["PROVIDER", "EchoProvider", "EchoSettings"]
