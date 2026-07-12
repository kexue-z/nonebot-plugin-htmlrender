"""Backend-neutral documents produced before renderer-specific execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Literal

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest


class RenderRequirement(str, Enum):
    """Execution features required by prepared content."""

    JAVASCRIPT = "javascript"
    NETWORK = "network"
    LOCAL_RESOURCE = "local_resource"


@dataclass(frozen=True, slots=True)
class PreparedAsset:
    """Binary resource addressable by its exact document URL."""

    source: str
    data: bytes
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedStylesheet:
    """One stylesheet with its own resource-resolution base."""

    css: str
    base_url: str | None = None
    embedded: bool = False
    media: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedHtml:
    """Canonical HTML payload shared by browser and native renderers.

    ``html`` always retains the original browser document. ``base_url`` is only a
    resource-resolution base; browser navigation is configured independently.
    """

    html: str
    stylesheets: tuple[PreparedStylesheet, ...] = ()
    base_url: str | None = None
    assets: tuple[PreparedAsset, ...] = ()
    requirements: frozenset[RenderRequirement] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class RasterOptions:
    """Portable raster options shared by HTML-capable engines."""

    width: int = 800
    height: int | None = None
    device_pixel_ratio: float = 2.0
    format: Literal["png", "jpeg"] = "png"
    quality: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or (self.height is not None and self.height <= 0):
            raise InvalidRenderRequest("Raster dimensions must be positive")
        if not math.isfinite(self.device_pixel_ratio) or self.device_pixel_ratio <= 0:
            raise InvalidRenderRequest("device_pixel_ratio must be finite and positive")
        if self.format not in {"png", "jpeg"}:
            raise InvalidRenderRequest("format must be 'png' or 'jpeg'")
        if self.quality is not None and self.format != "jpeg":
            raise InvalidRenderRequest("quality is only supported for JPEG output")
        if self.quality is not None and not 0 <= self.quality <= 100:
            raise InvalidRenderRequest("quality must be between 0 and 100")


__all__ = (
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "RasterOptions",
    "RenderRequirement",
)
