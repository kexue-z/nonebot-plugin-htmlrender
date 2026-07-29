from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from .runtime import TakumiRuntimeState, render_defaults
from .source import materialize_takumi_document

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nonebot_plugin_htmlrender.preparation import PreparedHtml, RasterOptions
    from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode

    from .types import StaticImageFormat, TakumiImageInput


def device_dimension(value: int | None, device_pixel_ratio: float) -> int | None:
    """Map a CSS-pixel dimension to Takumi's device-pixel canvas dimension."""
    if value is None:
        return None
    if value <= 0:
        raise ValueError("render dimensions must be greater than zero")
    return math.ceil(value * device_pixel_ratio)


def validate_device_pixel_ratio(value: float) -> float:
    ratio = float(value)
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError(
            "device_scale_factor must be a finite number greater than zero"
        )
    return ratio


async def render_prepared_html(
    state: TakumiRuntimeState,
    prepared: PreparedHtml,
    *,
    stylesheets: Sequence[str] = (),
    images: Sequence[TakumiImageInput | object] | None = None,
    width: int | None = 800,
    height: int | None = None,
    image_format: StaticImageFormat = "png",
    quality: int | None = None,
    device_pixel_ratio: float = 1.0,
    lossless: bool | None = None,
    font_size: float = 16.0,
    draw_debug_border: bool = False,
    time_ms: int = 0,
    dithering: Literal["none", "ordered-bayer", "floyd-steinberg"] = "none",
    lang: str | None = None,
    font_families: Sequence[str] | None = None,
    keyframes: object | None = None,
    resolve_mode: ResourceResolveMode | None = None,
) -> bytes:
    """Execute a backend-neutral prepared document with Takumi."""
    ratio = validate_device_pixel_ratio(device_pixel_ratio)
    document = await materialize_takumi_document(
        prepared,
        resources=state.resources,
        stylesheets=stylesheets,
        images=images,
        resolve_mode=resolve_mode,
    )
    native_options = render_defaults(state, images=document.images)
    native_options.update(
        width=device_dimension(width, ratio),
        height=device_dimension(height, ratio),
        format=image_format,
        font_size=font_size,
        device_pixel_ratio=ratio,
        draw_debug_border=draw_debug_border,
        time_ms=time_ms,
        dithering=dithering,
    )
    if quality is not None:
        native_options["quality"] = quality
    if lossless is not None:
        native_options["lossless"] = lossless
    if lang is not None:
        native_options["lang"] = lang
    if font_families is not None:
        native_options["font_families"] = tuple(font_families)
    if keyframes is not None:
        native_options["keyframes"] = keyframes

    rendered = await state.call_document(
        "render_compiled",
        document.html,
        document.stylesheets,
        **native_options,
    )
    if not isinstance(rendered, bytes):
        raise TypeError(f"Takumi returned {type(rendered).__name__}, expected bytes.")
    return rendered


async def rasterize_html(
    state: TakumiRuntimeState,
    prepared: PreparedHtml,
    options: RasterOptions,
    *,
    resolve_mode: ResourceResolveMode | None = None,
) -> bytes:
    return await render_prepared_html(
        state,
        prepared,
        width=options.width,
        height=options.height,
        image_format=options.format,
        quality=options.quality,
        device_pixel_ratio=options.device_pixel_ratio,
        resolve_mode=resolve_mode,
    )


__all__ = [
    "device_dimension",
    "rasterize_html",
    "render_prepared_html",
    "validate_device_pixel_ratio",
]
