from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.backend.playwright.models import (
    ContentConfig,
    HtmlRenderRequest,
    JpegScreenshotOptions,
    PageConfig,
    RenderConfig,
    ViewportConfig,
)
from nonebot_plugin_htmlrender.backend.takumi.errors import TakumiUnsupportedError
from nonebot_plugin_htmlrender.backend.takumi.operations import (
    rasterize_html,
    render_html,
    render_markdown,
    render_prepared_html,
    render_template,
    render_text,
)
from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_html

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.backend.takumi.runtime import TakumiRuntimeState


@dataclass
class _FakeConfig:
    font_families: list[str] = field(default_factory=list)
    default_lang: str | None = None


@dataclass
class _FakeState:
    config: _FakeConfig = field(default_factory=_FakeConfig)
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
    _, markup, stylesheets, options = state.calls[-1]
    assert markup == prepared.markup
    assert stylesheets == prepared.stylesheets
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


@pytest.mark.anyio
async def test_common_content_operations_consume_shared_preparation(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    state = _FakeState()
    prepared_text = prepare_html("<div>text-prepared</div>")
    prepared_markdown = prepare_html("<article>markdown-prepared</article>")
    prepared_template = prepare_html("<main>template-prepared</main>")
    prepare_text_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.operations.prepare_text",
        new=mocker.AsyncMock(return_value=prepared_text),
    )
    prepare_markdown_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.operations.prepare_markdown",
        new=mocker.AsyncMock(return_value=prepared_markdown),
    )
    prepare_template_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.operations.prepare_template",
        new=mocker.AsyncMock(return_value=prepared_template),
    )
    execute_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"image"),
    )

    assert (
        await render_text(
            _runtime_state(state),
            "hello",
            css_path="custom.css",
        )
        == b"image"
    )
    prepare_text_mock.assert_awaited_once_with("hello", css_path="custom.css")
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.args[1] is prepared_text

    assert (
        await render_markdown(
            _runtime_state(state),
            "# title",
            css_path="markdown.css",
        )
        == b"image"
    )
    prepare_markdown_mock.assert_awaited_once_with(
        "# title",
        markdown_path="",
        css_path="markdown.css",
    )
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.args[1] is prepared_markdown

    assert (
        await render_template(
            _runtime_state(state),
            str(tmp_path),
            template_name="card.html",
            templates={"name": "Takumi"},
        )
        == b"image"
    )
    prepare_template_mock.assert_awaited_once_with(
        str(tmp_path),
        "card.html",
        {"name": "Takumi"},
        filters=None,
    )
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.args[1] is prepared_template


@pytest.mark.anyio
async def test_html_request_maps_portable_screenshot_semantics() -> None:
    state = _FakeState()
    request = HtmlRenderRequest(
        content=ContentConfig(html="<main>hello</main>"),
        render=RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(width=320, height=180),
                base_url="https://example.com/base/",
            ),
            screenshot=JpegScreenshotOptions(
                quality=81,
                device_scale_factor=1.5,
                full_page=False,
            ),
        ),
    )

    await render_html(
        _runtime_state(state),
        request,
    )

    options = state.calls[-1][-1]
    assert options["width"] == 480
    assert options["height"] == 270
    assert options["format"] == "jpeg"
    assert options["quality"] == 81


@pytest.mark.anyio
async def test_browser_only_options_are_rejected() -> None:
    state = _FakeState()
    with pytest.raises(TakumiUnsupportedError, match="wait values must be zero"):
        await render_html(
            _runtime_state(state),
            "<div>ok</div>",
            wait=1,
        )

    with pytest.raises(TakumiUnsupportedError, match="unsupported options: locale"):
        await render_html(
            _runtime_state(state),
            "<div>ok</div>",
            locale="zh-CN",
        )

    request = HtmlRenderRequest(
        content=ContentConfig(html="<div>ok</div>"),
        render=RenderConfig(
            page=PageConfig(user_agent="browser"),
        ),
    )
    with pytest.raises(TakumiUnsupportedError, match="user_agent"):
        await render_html(
            _runtime_state(state),
            request,
        )
