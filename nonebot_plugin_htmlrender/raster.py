"""Backend-neutral raster contracts shared across preparation and rendering."""

from typing import Literal, TypeAlias

RasterImageFormat: TypeAlias = Literal["png", "jpeg"]

__all__ = ["RasterImageFormat"]
