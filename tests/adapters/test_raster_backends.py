from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
from typing_extensions import TypeAlias

from PIL import Image
import pytest

from nonebot_plugin_htmlrender.adapters.pillow import PillowRasterSceneRenderer
from nonebot_plugin_htmlrender.adapters.resources import AnyioWorkerExecutor
from nonebot_plugin_htmlrender.adapters.skia import SkiaRasterSceneRenderer
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    PixelRect,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)
from nonebot_plugin_htmlrender.graphics.execution import RasterWorkBudget
from nonebot_plugin_htmlrender.rendering import OperationAdmissionGate
from nonebot_plugin_htmlrender.rendering.observers import NoopOperationObserver

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.rendering import RenderedImage
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from tests.adapters.conftest import RecordingOperationObserver

RendererType: TypeAlias = (
    type[PillowRasterSceneRenderer] | type[SkiaRasterSceneRenderer]
)
Renderer: TypeAlias = PillowRasterSceneRenderer | SkiaRasterSceneRenderer


def _renderer(
    renderer_type: RendererType,
    *,
    observer: OperationObserver | None = None,
) -> Renderer:
    return renderer_type(
        worker=AnyioWorkerExecutor(),
        observer=observer if observer is not None else NoopOperationObserver(),
        operation_admission=OperationAdmissionGate(),
        budget=RasterWorkBudget(max_pixels=1_000_000, max_concurrency=2),
    )


def _pixel(
    image: RenderedImage,
    x: int,
    y: int,
    *,
    mode: str,
) -> tuple[int, ...]:
    with Image.open(BytesIO(image.data)) as decoded:
        value = decoded.convert(mode).getpixel((x, y))
    assert isinstance(value, tuple)
    return value


def _assert_channels_close(
    actual: tuple[int, ...],
    expected: tuple[int, ...],
    *,
    tolerance: int,
) -> None:
    assert len(actual) == len(expected)
    assert all(
        abs(actual_channel - expected_channel) <= tolerance
        for actual_channel, expected_channel in zip(actual, expected, strict=True)
    ), (actual, expected)


@pytest.mark.parametrize(
    ("renderer_type", "backend"),
    [
        pytest.param(PillowRasterSceneRenderer, "pillow", id="pillow"),
        pytest.param(SkiaRasterSceneRenderer, "skia", id="skia"),
    ],
)
async def test_raster_backend_renders_owned_scene_contract(
    renderer_type: RendererType,
    backend: str,
    operation_observer: RecordingOperationObserver,
) -> None:
    scene = RasterScene(
        4,
        3,
        background=RGBAColor(20, 40, 60, 128),
        commands=(
            FillRect(PixelRect(-1, 0, 3, 2), RGBAColor(220, 100, 40, 128)),
            FillRect(PixelRect(9, 9, 1, 1), RGBAColor(0, 0, 255)),
        ),
    )

    result = await _renderer(
        renderer_type,
        observer=operation_observer,
    ).render(RenderRasterSceneRequest(scene, RasterEncodeOptions()))

    assert (result.format, result.width, result.height) == ("png", 4, 3)
    _assert_channels_close(
        _pixel(result, 0, 0, mode="RGBA"),
        (153, 80, 47, 192),
        tolerance=1,
    )
    assert _pixel(result, 2, 1, mode="RGBA") == (20, 40, 60, 128)
    assert operation_observer.names() == [f"graphics.{backend}.render_scene"]


@pytest.mark.parametrize(
    "renderer_type",
    [
        pytest.param(PillowRasterSceneRenderer, id="pillow"),
        pytest.param(SkiaRasterSceneRenderer, id="skia"),
    ],
)
async def test_raster_backend_encodes_jpeg_over_matte(
    renderer_type: RendererType,
) -> None:
    matte = RGBAColor(10, 60, 180)
    scene = RasterScene(
        48,
        24,
        commands=(FillRect(PixelRect(8, 4, 16, 16), RGBAColor(220, 100, 40, 128)),),
    )

    result = await _renderer(renderer_type).render(
        RenderRasterSceneRequest(
            scene,
            RasterEncodeOptions(format="jpeg", quality=100, matte=matte),
        )
    )

    assert (result.format, result.width, result.height) == ("jpeg", 48, 24)
    _assert_channels_close(
        _pixel(result, 0, 0, mode="RGB"),
        (10, 60, 180),
        tolerance=3,
    )
    _assert_channels_close(
        _pixel(result, 12, 12, mode="RGB"),
        (115, 80, 110),
        tolerance=4,
    )
