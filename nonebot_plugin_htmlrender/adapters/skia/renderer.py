"""skia-python raster-scene adapter."""

# The local typed facade mirrors skia-python's public camelCase API exactly.
# ruff: noqa: N802, N803, N815

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast, final

from nonebot_plugin_htmlrender.graphics.execution import run_raster_backend
from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.graphics.execution import RasterWorkBudget
    from nonebot_plugin_htmlrender.graphics.models import (
        RenderRasterSceneRequest,
        RGBAColor,
    )
    from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.resources.ports import WorkerExecutor


class _SkiaData(Protocol):
    def __bytes__(self) -> bytes: ...


class _SkiaImage(Protocol):
    def encodeToData(self, image_format: object, quality: int) -> _SkiaData | None: ...


class _SkiaPaint(Protocol):
    def setColor(self, color: int) -> None: ...

    def setBlendMode(self, blend_mode: object) -> None: ...


class _SkiaCanvas(Protocol):
    def clear(self, color: int) -> None: ...

    def drawRect(self, rect: object, paint: _SkiaPaint) -> None: ...

    def drawImage(
        self,
        image: _SkiaImage,
        x: float,
        y: float,
        sampling: object,
        paint: _SkiaPaint,
    ) -> None: ...


class _SkiaSurface(Protocol):
    def getCanvas(self) -> _SkiaCanvas: ...

    def makeImageSnapshot(self) -> _SkiaImage: ...


class _Factory(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...


class _PaintFactory(Protocol):
    def __call__(
        self,
        *,
        AntiAlias: bool = False,
    ) -> _SkiaPaint: ...


class _ImageInfoFactory(Protocol):
    def Make(
        self,
        width: int,
        height: int,
        color_type: object,
        alpha_type: object,
        color_space: object,
    ) -> object: ...


class _SurfaceFactory(Protocol):
    def MakeRaster(self, info: object) -> _SkiaSurface | None: ...


class _RectFactory(Protocol):
    def MakeXYWH(self, x: int, y: int, width: int, height: int) -> object: ...


class _ColorSpaceFactory(Protocol):
    def MakeSRGB(self) -> object: ...


class _ColorTypeValues(Protocol):
    kRGBA_8888_ColorType: object


class _AlphaTypeValues(Protocol):
    kPremul_AlphaType: object


class _BlendModeValues(Protocol):
    kSrcOver: object


class _EncodedImageFormatValues(Protocol):
    kPNG: object
    kJPEG: object


class _SkiaModule(Protocol):
    ImageInfo: _ImageInfoFactory
    Surface: _SurfaceFactory
    Rect: _RectFactory
    ColorSpace: _ColorSpaceFactory
    Paint: _PaintFactory
    SamplingOptions: _Factory
    ColorType: _ColorTypeValues
    AlphaType: _AlphaTypeValues
    BlendMode: _BlendModeValues
    EncodedImageFormat: _EncodedImageFormatValues

    def ColorSetARGB(self, alpha: int, red: int, green: int, blue: int) -> int: ...


_skia = cast("_SkiaModule", import_module("skia"))


def _skia_color(color: RGBAColor) -> int:
    return _skia.ColorSetARGB(color.alpha, color.red, color.green, color.blue)


def _surface(width: int, height: int) -> _SkiaSurface:
    info = _skia.ImageInfo.Make(
        width,
        height,
        _skia.ColorType.kRGBA_8888_ColorType,
        _skia.AlphaType.kPremul_AlphaType,
        _skia.ColorSpace.MakeSRGB(),
    )
    surface = _skia.Surface.MakeRaster(info)
    if surface is None:
        raise RuntimeError("Skia could not allocate an RGBA raster surface.")
    return surface


def _encode(image: _SkiaImage, request: RenderRasterSceneRequest) -> bytes:
    if request.output.format == "png":
        data = image.encodeToData(_skia.EncodedImageFormat.kPNG, 100)
    else:
        data = image.encodeToData(
            _skia.EncodedImageFormat.kJPEG,
            request.output.jpeg_quality,
        )
    if data is None:
        raise RuntimeError(f"Skia could not encode {request.output.format.upper()}.")
    return bytes(data)


def _render_sync(request: RenderRasterSceneRequest) -> RenderedImage:
    scene = request.scene
    surface = _surface(scene.width, scene.height)
    canvas = surface.getCanvas()
    canvas.clear(_skia_color(scene.background))

    for command in scene.commands:
        rect = command.rect.clipped_to(scene.width, scene.height)
        if rect is None:
            continue
        paint = _skia.Paint(AntiAlias=False)
        paint.setColor(_skia_color(command.color))
        paint.setBlendMode(_skia.BlendMode.kSrcOver)
        canvas.drawRect(
            _skia.Rect.MakeXYWH(rect.x, rect.y, rect.width, rect.height),
            paint,
        )

    image = surface.makeImageSnapshot()
    if request.output.format == "jpeg":
        matte_surface = _surface(scene.width, scene.height)
        matte_canvas = matte_surface.getCanvas()
        matte_canvas.clear(_skia_color(request.output.jpeg_matte))
        matte_paint = _skia.Paint(AntiAlias=False)
        matte_paint.setBlendMode(_skia.BlendMode.kSrcOver)
        matte_canvas.drawImage(
            image,
            0,
            0,
            _skia.SamplingOptions(),
            matte_paint,
        )
        image = matte_surface.makeImageSnapshot()

    return RenderedImage.from_bytes(
        _encode(image, request),
        expected_format=request.output.format,
    )


@final
class SkiaRasterSceneRenderer:
    """Render neutral scenes through skia-python on an injected worker thread."""

    def __init__(
        self,
        *,
        worker: WorkerExecutor,
        observer: OperationObserver,
        operation_admission: OperationAdmissionGate,
        budget: RasterWorkBudget,
    ) -> None:
        self._worker = worker
        self._observer = observer
        self._operation_admission = operation_admission
        self._budget = budget

    async def render(self, request: RenderRasterSceneRequest) -> RenderedImage:
        return await run_raster_backend(
            "skia",
            request,
            _render_sync,
            worker=self._worker,
            observer=self._observer,
            operation_admission=self._operation_admission,
            budget=self._budget,
        )


__all__ = ["SkiaRasterSceneRenderer"]
