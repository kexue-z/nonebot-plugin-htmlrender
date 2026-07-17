"""Immutable, backend-neutral values for physical-pixel raster scenes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.raster import RasterImageFormat  # noqa: TC001

GraphicsBackendName: TypeAlias = Literal["pillow", "skia"]


def _require_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise InvalidRenderRequest(f"{name} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class RGBAColor:
    """Straight-alpha, 8-bit sRGB input color.

    Adapters may use premultiplied native storage. RGB channels are not
    observable when alpha is zero and need not survive an encode round trip.
    """

    red: int
    green: int
    blue: int
    alpha: int = 255

    def __post_init__(self) -> None:
        for name, value in (
            ("red", self.red),
            ("green", self.green),
            ("blue", self.blue),
            ("alpha", self.alpha),
        ):
            channel = _require_int(name, value)
            if not 0 <= channel <= 255:
                raise InvalidRenderRequest(f"{name} must be between 0 and 255")

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.red, self.green, self.blue, self.alpha


TRANSPARENT = RGBAColor(0, 0, 0, 0)
OPAQUE_WHITE = RGBAColor(255, 255, 255)


@dataclass(frozen=True, slots=True)
class PixelRect:
    """Half-open, integer-pixel rectangle that may extend beyond a scene."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            _require_int(name, value)
        if self.width <= 0 or self.height <= 0:
            raise InvalidRenderRequest("rectangle dimensions must be positive")

    def clipped_to(self, width: int, height: int) -> PixelRect | None:
        """Intersect this rectangle with a canvas using half-open bounds."""
        canvas_width = _require_int("canvas width", width)
        canvas_height = _require_int("canvas height", height)
        if canvas_width <= 0 or canvas_height <= 0:
            raise InvalidRenderRequest("canvas dimensions must be positive")
        left = max(0, self.x)
        top = max(0, self.y)
        right = min(canvas_width, self.x + self.width)
        bottom = min(canvas_height, self.y + self.height)
        if right <= left or bottom <= top:
            return None
        return PixelRect(left, top, right - left, bottom - top)


@dataclass(frozen=True, slots=True)
class FillRect:
    """Paint one rectangle using conceptual Porter-Duff source-over.

    Native backends control their 8-bit premultiplication and quantization.
    Cross-backend encoded bytes and exact channel values are not equivalent
    output contracts.
    """

    rect: PixelRect
    color: RGBAColor

    def __post_init__(self) -> None:
        if not isinstance(self.rect, PixelRect):
            raise InvalidRenderRequest("FillRect.rect must be a PixelRect")
        if not isinstance(self.color, RGBAColor):
            raise InvalidRenderRequest("FillRect.color must be an RGBAColor")


@dataclass(frozen=True, slots=True)
class RasterScene:
    """Physical-pixel scene shared by raster drawing backends.

    Commands execute in tuple order, clip to the canvas, and use conceptual
    source-over composition over 8-bit sRGB inputs. Native premultiplication,
    channel quantization, and encoders may differ, so scenes do not promise
    byte-for-byte or pixel-identical output across backends. The first contract
    intentionally contains only solid, integer-aligned rectangles: it does not
    pretend to provide HTML layout, text shaping, or backend-native transport.
    """

    width: int
    height: int
    background: RGBAColor = TRANSPARENT
    commands: tuple[FillRect, ...] = ()

    def __post_init__(self) -> None:
        canvas_width = _require_int("scene width", self.width)
        canvas_height = _require_int("scene height", self.height)
        if canvas_width <= 0 or canvas_height <= 0:
            raise InvalidRenderRequest("scene dimensions must be positive")
        if not isinstance(self.background, RGBAColor):
            raise InvalidRenderRequest("scene background must be an RGBAColor")
        if not isinstance(self.commands, tuple) or not all(
            isinstance(command, FillRect) for command in self.commands
        ):
            raise InvalidRenderRequest("scene commands must be a tuple of FillRect")


@dataclass(frozen=True, slots=True)
class RasterEncodeOptions:
    """Backend-neutral PNG/JPEG encoding semantics for a raster scene.

    JPEG first composites the complete RGBA scene source-over onto the opaque
    matte. ``quality`` is the common encoder input, not a promise that native
    encoders produce equivalent compression or bytes.
    """

    format: RasterImageFormat = "png"
    quality: int | None = None
    matte: RGBAColor | None = None

    def __post_init__(self) -> None:
        if self.format not in {"png", "jpeg"}:
            raise InvalidRenderRequest("format must be 'png' or 'jpeg'")
        if self.quality is not None:
            quality = _require_int("quality", self.quality)
            if self.format != "jpeg":
                raise InvalidRenderRequest("quality is only supported for JPEG output")
            if not 0 <= quality <= 100:
                raise InvalidRenderRequest("quality must be between 0 and 100")
        if self.matte is not None:
            if not isinstance(self.matte, RGBAColor):
                raise InvalidRenderRequest("matte must be an RGBAColor")
            if self.format != "jpeg":
                raise InvalidRenderRequest("matte is only supported for JPEG output")
            if self.matte.alpha != 255:
                raise InvalidRenderRequest("JPEG matte must be opaque")

    @property
    def jpeg_quality(self) -> int:
        """Resolve the common JPEG encoder input used by every adapter."""
        return 90 if self.quality is None else self.quality

    @property
    def jpeg_matte(self) -> RGBAColor:
        """Resolve the opaque destination beneath the complete RGBA scene."""
        return OPAQUE_WHITE if self.matte is None else self.matte


@dataclass(frozen=True, slots=True)
class RenderRasterSceneRequest:
    """One complete raster-scene render request."""

    scene: RasterScene
    output: RasterEncodeOptions = field(default_factory=RasterEncodeOptions)

    def __post_init__(self) -> None:
        if not isinstance(self.scene, RasterScene):
            raise InvalidRenderRequest("scene must be a RasterScene")
        if not isinstance(self.output, RasterEncodeOptions):
            raise InvalidRenderRequest("output must be RasterEncodeOptions")


__all__ = [
    "OPAQUE_WHITE",
    "TRANSPARENT",
    "FillRect",
    "GraphicsBackendName",
    "PixelRect",
    "RGBAColor",
    "RasterEncodeOptions",
    "RasterScene",
    "RenderRasterSceneRequest",
]
