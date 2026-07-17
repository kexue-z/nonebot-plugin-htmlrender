"""Ports implemented by independent raster-scene adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Public protocol annotations must remain resolvable through get_type_hints().
from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage  # noqa: TC001

from .models import RenderRasterSceneRequest  # noqa: TC001


@runtime_checkable
class RasterSceneRenderer(Protocol):
    """Render a neutral physical-pixel scene without exposing native objects."""

    async def render(self, request: RenderRasterSceneRequest) -> RenderedImage: ...


__all__ = ["RasterSceneRenderer"]
