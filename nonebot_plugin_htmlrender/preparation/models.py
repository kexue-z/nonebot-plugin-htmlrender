"""Backend-neutral documents produced before renderer-specific execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Literal


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
class PreparedHtml:
    """Canonical HTML payload shared by browser and native renderers.

    ``html`` retains the original document for browser engines. ``markup`` removes
    document-level style blocks for engines that accept CSS separately.
    """

    html: str
    markup: str
    stylesheets: tuple[str, ...] = ()
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
            raise ValueError("Raster dimensions must be positive")
        if not math.isfinite(self.device_pixel_ratio) or self.device_pixel_ratio <= 0:
            raise ValueError("device_pixel_ratio must be finite and positive")
        if self.quality is not None and not 0 <= self.quality <= 100:
            raise ValueError("quality must be between 0 and 100")


__all__ = ("PreparedAsset", "PreparedHtml", "RasterOptions", "RenderRequirement")
