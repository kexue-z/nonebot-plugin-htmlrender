from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.adapters.takumi.operations import (
    rasterize_html,
    render_prepared_html,
)
from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_html

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.adapters.takumi.runtime import TakumiRuntimeState
    from nonebot_plugin_htmlrender.resources.service import ResourceService

from tests.adapters.takumi.helpers import resource_service


@dataclass
class _FakeConfig:
    font_families: list[str] = field(default_factory=list)
    default_lang: str | None = None


@dataclass
class _FakeState:
    config: _FakeConfig = field(default_factory=_FakeConfig)
    resources: ResourceService = field(default_factory=resource_service)
    calls: list[tuple[str, str, tuple[str, ...], dict[str, object]]] = field(
        default_factory=list
    )

    async def call_document(
        self,
        method: str,
        markup: str,
        stylesheets: tuple[str, ...],
        **kwargs: object,
    ) -> bytes:
        self.calls.append((method, markup, stylesheets, kwargs))
        return b"rendered"


def _runtime_state(state: _FakeState) -> TakumiRuntimeState:
    return cast("TakumiRuntimeState", state)


@pytest.mark.anyio
async def test_rasterize_html_maps_logical_dimensions_and_keeps_auto_height() -> None:
    state = _FakeState()
    prepared = prepare_html("<style>div { color:red }</style><div>ok</div>")

    result = await rasterize_html(
        _runtime_state(state),
        prepared,
        RasterOptions(width=96, height=None, device_pixel_ratio=2),
    )

    assert result == b"rendered"
    _, html, stylesheets, options = state.calls[-1]
    assert html == prepared.html
    assert stylesheets == tuple(stylesheet.css for stylesheet in prepared.stylesheets)
    assert options["width"] == 192
    assert options["height"] is None
    assert options["device_pixel_ratio"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("width", "ratio"),
    [(0, 1.0), (-1, 1.0), (10, 0.0), (10, float("inf")), (10, float("nan"))],
)
async def test_invalid_dimensions_and_device_ratios_are_rejected(
    width: int,
    ratio: float,
) -> None:
    with pytest.raises(ValueError):
        await render_prepared_html(
            _runtime_state(_FakeState()),
            prepare_html("<div>ok</div>"),
            width=width,
            device_pixel_ratio=ratio,
        )


@pytest.mark.anyio
async def test_render_prepared_html_forwards_explicit_native_options() -> None:
    state = _FakeState(_FakeConfig(font_families=["Configured"], default_lang="zh"))

    await render_prepared_html(
        _runtime_state(state),
        prepare_html("<div>ok</div>"),
        width=30,
        height=20,
        image_format="webp",
        quality=73,
        lossless=True,
        device_pixel_ratio=1.5,
        font_families=["Override"],
        lang="ja",
    )

    options = state.calls[-1][-1]
    assert options == {
        "font_families": ("Override",),
        "lang": "ja",
        "images": (),
        "width": 45,
        "height": 30,
        "format": "webp",
        "font_size": 16.0,
        "device_pixel_ratio": 1.5,
        "draw_debug_border": False,
        "time_ms": 0,
        "dithering": "none",
        "quality": 73,
        "lossless": True,
    }
