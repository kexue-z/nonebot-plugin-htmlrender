from __future__ import annotations

from functools import cache
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from nonebot_plugin_htmlrender.rendering import RenderedImage

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.raster import RasterImageFormat


@cache
def encoded_image(
    image_format: RasterImageFormat = "png",
    *,
    width: int = 1,
    height: int = 1,
    progressive: bool = False,
) -> bytes:
    stream = BytesIO()
    image = Image.new("RGB", (width, height), color=(12, 34, 56))
    if image_format == "jpeg":
        image.save(stream, format="JPEG", progressive=progressive)
    else:
        if progressive:
            raise ValueError("progressive encoding is only available for JPEG")
        image.save(stream, format="PNG")
    return stream.getvalue()


def rendered_image(
    image_format: RasterImageFormat = "png",
    *,
    width: int = 1,
    height: int = 1,
) -> RenderedImage:
    return RenderedImage.from_bytes(
        encoded_image(image_format, width=width, height=height),
        expected_format=image_format,
    )


__all__ = ["encoded_image", "rendered_image"]
