from __future__ import annotations

from typing import get_type_hints

from nonebot_plugin_htmlrender.graphics import (
    PILLOW_RASTER_SCENE_RENDERER,
    SKIA_RASTER_SCENE_RENDERER,
    RasterSceneRenderer,
    RenderRasterSceneRequest,
)
from nonebot_plugin_htmlrender.rendering import CapabilityCatalog, RenderedImage


class _Renderer:
    async def render(self, request: RenderRasterSceneRequest) -> RenderedImage:
        del request
        raise NotImplementedError


def test_pillow_and_skia_have_distinct_typed_capability_keys() -> None:
    pillow = _Renderer()
    skia = _Renderer()
    assert isinstance(pillow, RasterSceneRenderer)
    assert isinstance(skia, RasterSceneRenderer)

    catalog = (
        CapabilityCatalog()
        .with_capability(PILLOW_RASTER_SCENE_RENDERER, pillow)
        .with_capability(SKIA_RASTER_SCENE_RENDERER, skia)
    )

    assert catalog.require(PILLOW_RASTER_SCENE_RENDERER) is pillow
    assert catalog.require(SKIA_RASTER_SCENE_RENDERER) is skia
    assert PILLOW_RASTER_SCENE_RENDERER.name != SKIA_RASTER_SCENE_RENDERER.name


def test_public_renderer_annotations_are_runtime_resolvable() -> None:
    annotations = get_type_hints(RasterSceneRenderer.render)

    assert annotations == {
        "request": RenderRasterSceneRequest,
        "return": RenderedImage,
    }
