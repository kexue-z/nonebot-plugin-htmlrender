from __future__ import annotations

from importlib.metadata import version
import struct
from typing import TYPE_CHECKING, cast

import anyio
import pytest

takumi_py = pytest.importorskip("takumi_py")

from nonebot_plugin_htmlrender.backend.takumi import TakumiConfig
from nonebot_plugin_htmlrender.backend.takumi.api import (
    TakumiExtension,
)
from nonebot_plugin_htmlrender.backend.takumi.operations import (
    render_markdown,
    render_template,
    render_text,
)
from nonebot_plugin_htmlrender.backend.takumi.runtime import (
    create_runtime_state,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    prepare_html,
)

if TYPE_CHECKING:
    from pathlib import Path


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def _node(color: str = "#ff0000") -> dict[str, object]:
    return {
        "type": "container",
        "style": {
            "display": "flex",
            "width": 48,
            "height": 24,
            "backgroundColor": color,
        },
    }


def test_exact_takumi_version_is_installed() -> None:
    assert version("takumi-py") == "0.2.0"


@pytest.mark.anyio
async def test_html_node_compiled_measure_and_svg_capabilities() -> None:
    state = await create_runtime_state(TakumiConfig())
    try:
        extension = TakumiExtension(state)
        html = (
            "<style>body { margin: 0 } .box { width: 96px; height: 48px; "
            'background: #f00 }</style><div class="box"></div>'
        )
        rendered = await extension.render_html(
            html,
            width=96,
            height=48,
            device_pixel_ratio=2,
        )
        assert _png_size(rendered) == (192, 96)

        node_rendered = await extension.render_node(
            _node(),
            width=48,
            height=24,
            device_pixel_ratio=2,
        )
        assert _png_size(node_rendered) == (96, 48)

        measured = await extension.measure_node(
            _node(),
            width=48,
            height=24,
            device_pixel_ratio=2,
        )
        assert measured.width == 96
        assert measured.height == 48

        svg = await extension.render_svg_node(_node(), width=48, height=24)
        assert svg.startswith("<svg")
        assert "48" in svg and "24" in svg

        compiled = await extension.compile_html(
            '<div style="width:32px;height:16px;background:#00f"></div>'
        )
        compiled_rendered = await extension.render_compiled(
            compiled,
            width=32,
            height=16,
            device_pixel_ratio=2,
        )
        assert _png_size(compiled_rendered) == (64, 32)
    finally:
        await state.aclose()


@pytest.mark.anyio
async def test_native_css_media_at_rule_keeps_conditional_behavior() -> None:
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    state = await create_runtime_state(TakumiConfig())
    try:
        extension = TakumiExtension(state)
        html = (
            "<style>body { margin: 0 } .box { width: 20px; height: 20px; "
            "background: #f00 } @media (max-width: 767px) { "
            ".box { background: #00f } }</style>"
            '<div class="box"></div>'
        )

        narrow = await extension.render_html(html, width=500, height=20)
        wide = await extension.render_html(html, width=800, height=20)
        narrow_pixel = cast(
            "tuple[int, int, int, int]",
            Image.open(BytesIO(narrow)).convert("RGBA").getpixel((10, 10)),
        )
        wide_pixel = cast(
            "tuple[int, int, int, int]",
            Image.open(BytesIO(wide)).convert("RGBA").getpixel((10, 10)),
        )

        assert narrow_pixel[:3] == (0, 0, 255)
        assert wide_pixel[:3] == (255, 0, 0)
    finally:
        await state.aclose()


@pytest.mark.anyio
async def test_native_renderer_handles_bounded_concurrent_documents() -> None:
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    colors = (
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (128, 64, 32),
        (32, 64, 128),
    )
    results: list[bytes | None] = [None] * len(colors)
    state = await create_runtime_state(TakumiConfig(max_concurrency=4))
    try:
        extension = TakumiExtension(state)

        async def _render(index: int, color: tuple[int, int, int]) -> None:
            red, green, blue = color
            html = (
                '<div style="width:16px;height:16px;'
                f'background:rgb({red},{green},{blue})"></div>'
            )
            results[index] = await extension.render_html(
                html,
                width=16,
                height=16,
            )

        async with anyio.create_task_group() as task_group:
            for index, color in enumerate(colors):
                task_group.start_soon(_render, index, color)

        for expected, payload in zip(colors, results, strict=True):
            assert payload is not None
            assert _png_size(payload) == (16, 16)
            image = Image.open(BytesIO(payload)).convert("RGB")
            assert image.getpixel((8, 8)) == expected
    finally:
        await state.aclose()


@pytest.mark.anyio
async def test_static_formats_and_prepared_asset_cross_native_boundary() -> None:
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    state = await create_runtime_state(TakumiConfig())
    try:
        extension = TakumiExtension(state)
        png = await extension.render_node(_node(), width=48, height=24)
        jpeg = await extension.render_node(_node(), width=48, height=24, format="jpeg")
        webp = await extension.render_node(_node(), width=48, height=24, format="webp")
        jpg = await extension.render_node(_node(), width=48, height=24, format="jpg")
        ico = await extension.render_node(_node(), width=48, height=24, format="ico")
        raw = await extension.render_node(_node(), width=48, height=24, format="raw")
        assert png.startswith(b"\x89PNG")
        assert jpeg.startswith(b"\xff\xd8")
        assert webp.startswith(b"RIFF") and webp[8:12] == b"WEBP"
        assert jpg.startswith(b"\xff\xd8")
        assert ico.startswith(b"\x00\x00\x01\x00")
        assert len(raw) == 48 * 24 * 4

        avatar = await extension.render_node(
            {
                "type": "container",
                "style": {"width": 4, "height": 4, "backgroundColor": "#00ff00"},
            },
            width=4,
            height=4,
        )
        prepared = prepare_html(
            '<img src="memory:avatar" width="4" height="4">',
            assets=(PreparedAsset("memory:avatar", avatar, "image/png"),),
        )
        composed = await extension.render_html(prepared, width=4, height=4)
        image = Image.open(BytesIO(composed)).convert("RGBA")
        pixel = cast("tuple[int, int, int, int]", image.getpixel((2, 2)))
        assert pixel[1] > 200

        canonical = prepare_html(
            '<img src="./avatar.png" width="4" height="4">',
            base_url="https://example.test/cards/card.html",
            assets=(
                PreparedAsset(
                    "https://example.test/cards/avatar.png",
                    avatar,
                    "image/png",
                ),
            ),
        )
        canonical_composed = await extension.render_html(canonical, width=4, height=4)
        canonical_image = Image.open(BytesIO(canonical_composed)).convert("RGBA")
        canonical_pixel = cast(
            "tuple[int, int, int, int]",
            canonical_image.getpixel((2, 2)),
        )
        assert canonical_pixel[1] > 200

        red_avatar = await extension.render_node(
            {
                "type": "container",
                "style": {"width": 4, "height": 4, "backgroundColor": "#ff0000"},
            },
            width=4,
            height=4,
        )
        for payload, channel in ((red_avatar, 0), (avatar, 1)):
            changing = prepare_html(
                '<img src="memory:changing" width="4" height="4">',
                assets=(PreparedAsset("memory:changing", payload, "image/png"),),
            )
            changed = await extension.render_html(changing, width=4, height=4)
            changed_image = Image.open(BytesIO(changed)).convert("RGBA")
            changed_pixel = cast(
                "tuple[int, int, int, int]",
                changed_image.getpixel((2, 2)),
            )
            assert changed_pixel[channel] > 200
    finally:
        await state.aclose()


@pytest.mark.anyio
async def test_animation_sequence_and_raw_frame_encoding() -> None:
    from takumi_py import AnimationScene, RawAnimationFrame  # noqa: PLC0415

    state = await create_runtime_state(TakumiConfig())
    try:
        extension = TakumiExtension(state)
        scenes = [
            AnimationScene(_node("#ff0000"), 100),
            AnimationScene(_node("#0000ff"), 100),
        ]
        webp = await extension.render_animation(
            scenes,
            width=48,
            height=24,
            fps=10,
            format="webp",
        )
        apng = await extension.render_animation(
            scenes,
            width=48,
            height=24,
            fps=10,
            format="apng",
        )
        gif = await extension.render_animation(
            scenes,
            width=48,
            height=24,
            fps=10,
            format="gif",
        )
        assert webp.startswith(b"RIFF") and webp[8:12] == b"WEBP"
        assert apng.startswith(b"\x89PNG")
        assert gif.startswith((b"GIF87a", b"GIF89a"))

        sample = await extension.render_sequence_at_time(
            scenes,
            120,
            width=48,
            height=24,
        )
        assert _png_size(sample) == (48, 24)

        frame = RawAnimationFrame(
            bytes((255, 0, 0, 255)) * 4,
            width=2,
            height=2,
            duration_ms=100,
        )
        encoded = await extension.encode_frames([frame], format="gif")
        assert encoded.startswith((b"GIF87a", b"GIF89a"))
    finally:
        await state.aclose()


@pytest.mark.anyio
async def test_shared_text_markdown_and_template_preparation(
    tmp_path: Path,
) -> None:
    state = await create_runtime_state(TakumiConfig())
    try:
        text = await render_text(
            state,
            "你好 <tag> & text",
            width=240,
            device_scale_factor=1,
        )
        markdown = await render_markdown(
            state,
            "# 标题\n\n`<tag>`",
            width=360,
            device_scale_factor=1,
        )

        (tmp_path / "card.html").write_text(
            '<div style="width:80px;height:30px;background:#fff">{{ value }}</div>',
            encoding="utf-8",
        )
        template = await render_template(
            state,
            str(tmp_path),
            template_name="card.html",
            templates={"value": "<unsafe> & Unicode 字符"},
            device_scale_factor=1,
        )

        assert text.startswith(b"\x89PNG")
        assert markdown.startswith(b"\x89PNG")
        assert template.startswith(b"\x89PNG")
    finally:
        await state.aclose()
