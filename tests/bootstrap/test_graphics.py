from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.bootstrap.composition import prepare_runtime
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    GraphicsBackendName,
    PixelRect,
    RasterBackendUnavailable,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)
from nonebot_plugin_htmlrender.rendering import ProviderLifecycleError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _settings(*backends: GraphicsBackendName) -> RenderSettings:
    return RenderSettings.model_validate(
        {
            "graphics": {
                "backends": backends,
                "max_pixels": 64,
                "max_concurrency": 1,
            }
        }
    )


def _request() -> RenderRasterSceneRequest:
    return RenderRasterSceneRequest(
        RasterScene(
            4,
            3,
            background=RGBAColor(0, 0, 0, 0),
            commands=(FillRect(PixelRect(1, 1, 2, 1), RGBAColor(255, 0, 0)),),
        )
    )


async def test_both_graphics_backends_compose_without_an_html_provider() -> None:
    application = prepare_runtime(_settings("pillow", "skia")).build_application()
    pillow = application.extensions.pillow
    skia = application.extensions.skia

    try:
        pillow_image = await pillow.render(_request())
        skia_image = await skia.render(_request())
    finally:
        await application.aclose()

    assert (pillow_image.format, pillow_image.width, pillow_image.height) == (
        "png",
        4,
        3,
    )
    assert (skia_image.format, skia_image.width, skia_image.height) == (
        "png",
        4,
        3,
    )
    assert application.renderer.supported_commands == frozenset(
        {"render_template_html"}
    )


async def test_retained_graphics_capabilities_share_application_admission() -> None:
    application = prepare_runtime(_settings("pillow", "skia")).build_application()
    pillow = application.extensions.pillow
    skia = application.extensions.skia

    await application.aclose()

    for renderer in (pillow, skia):
        with pytest.raises(ProviderLifecycleError, match="closing or closed"):
            await renderer.render(_request())


def test_configured_missing_graphics_extra_fails_with_install_hint(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.bootstrap.graphics.find_spec",
        return_value=None,
    )

    with pytest.raises(
        RasterBackendUnavailable,
        match=r"nonebot-plugin-htmlrender\[pillow\]",
    ):
        prepare_runtime(_settings("pillow")).build_application()
