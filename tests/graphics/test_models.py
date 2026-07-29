from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    PixelRect,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)
from nonebot_plugin_htmlrender.graphics.errors import (
    RasterBackendExecutionError,
    RasterBackendUnavailable,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def test_scene_is_deeply_immutable_and_uses_half_open_clipping() -> None:
    color = RGBAColor(10, 20, 30, 128)
    rect = PixelRect(-2, 3, 7, 8)
    command = FillRect(rect, color)
    scene = RasterScene(10, 10, commands=(command,))

    assert color.as_tuple() == (10, 20, 30, 128)
    assert rect.clipped_to(scene.width, scene.height) == PixelRect(0, 3, 5, 7)
    assert PixelRect(20, 20, 1, 1).clipped_to(10, 10) is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RGBAColor(red=True, green=0, blue=0),
        lambda: RGBAColor(256, 0, 0),
        lambda: PixelRect(0, 0, 0, 1),
        lambda: RasterScene(0, 1),
        lambda: RasterScene(1, 1, commands=cast("tuple[FillRect, ...]", [])),
        lambda: RasterEncodeOptions(format="png", quality=90),
        lambda: RasterEncodeOptions(
            format="jpeg",
            matte=RGBAColor(0, 0, 0, 1),
        ),
    ],
)
def test_invalid_scene_values_fail_at_the_contract_boundary(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(InvalidRenderRequest):
        factory()


def test_jpeg_defaults_are_backend_independent() -> None:
    output = RasterEncodeOptions(format="jpeg")
    request = RenderRasterSceneRequest(RasterScene(4, 3), output)

    assert request.output.jpeg_quality == 90
    assert request.output.jpeg_matte == RGBAColor(255, 255, 255)


@pytest.mark.parametrize(
    "error_type",
    [RasterBackendExecutionError, RasterBackendUnavailable],
)
def test_raster_backend_errors_preserve_typed_backend_name(
    error_type: type[RasterBackendExecutionError | RasterBackendUnavailable],
) -> None:
    error = error_type("pillow", "missing")

    assert error.backend == "pillow"
