"""Backend-neutral raster scene contracts and typed backend capabilities."""

from .capabilities import (
    PILLOW_RASTER_SCENE_RENDERER as PILLOW_RASTER_SCENE_RENDERER,
)
from .capabilities import SKIA_RASTER_SCENE_RENDERER as SKIA_RASTER_SCENE_RENDERER
from .errors import RasterBackendExecutionError as RasterBackendExecutionError
from .errors import RasterBackendUnavailable as RasterBackendUnavailable
from .models import FillRect as FillRect
from .models import GraphicsBackendName as GraphicsBackendName
from .models import PixelRect as PixelRect
from .models import RasterEncodeOptions as RasterEncodeOptions
from .models import RasterScene as RasterScene
from .models import RenderRasterSceneRequest as RenderRasterSceneRequest
from .models import RGBAColor as RGBAColor
from .ports import RasterSceneRenderer as RasterSceneRenderer

__all__ = [
    "PILLOW_RASTER_SCENE_RENDERER",
    "SKIA_RASTER_SCENE_RENDERER",
    "FillRect",
    "GraphicsBackendName",
    "PixelRect",
    "RGBAColor",
    "RasterBackendExecutionError",
    "RasterBackendUnavailable",
    "RasterEncodeOptions",
    "RasterScene",
    "RasterSceneRenderer",
    "RenderRasterSceneRequest",
]
