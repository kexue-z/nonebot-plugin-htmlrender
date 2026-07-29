"""Typed keys for independently composed raster-scene backends."""

from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

from .ports import RasterSceneRenderer

PILLOW_RASTER_SCENE_RENDERER = CapabilityKey(
    "graphics.pillow.raster_scene_renderer",
    RasterSceneRenderer,
)
SKIA_RASTER_SCENE_RENDERER = CapabilityKey(
    "graphics.skia.raster_scene_renderer",
    RasterSceneRenderer,
)

__all__ = ["PILLOW_RASTER_SCENE_RENDERER", "SKIA_RASTER_SCENE_RENDERER"]
