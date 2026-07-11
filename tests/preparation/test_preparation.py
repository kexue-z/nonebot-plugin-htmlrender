from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    RasterOptions,
    RenderRequirement,
    prepare_html,
    prepare_markdown,
    prepare_template,
    prepare_text,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_prepare_html_preserves_browser_document_and_extracts_native_css() -> None:
    prepared = prepare_html(
        "<style>.card { color: red }</style><main class='card'>ok</main>",
        stylesheets=[".logo { background: url(https://cdn.example/logo.png) }"],
        assets=[PreparedAsset("memory://icon", b"icon", "image/png")],
    )

    assert "<style>" in prepared.html
    assert [stylesheet.css for stylesheet in prepared.stylesheets] == [
        ".logo { background: url(https://cdn.example/logo.png) }",
        ".card { color: red }",
    ]
    assert prepared.stylesheets[0].embedded is False
    assert prepared.stylesheets[1].embedded is True
    assert prepared.assets[0].source == "memory://icon"
    assert RenderRequirement.NETWORK in prepared.requirements


def test_prepare_html_detects_script_and_local_resources() -> None:
    prepared = prepare_html(
        '<script>run()</script><img src="./avatar.png">',
    )
    assert prepared.requirements == frozenset(
        {RenderRequirement.JAVASCRIPT, RenderRequirement.LOCAL_RESOURCE}
    )


def test_prepare_html_classifies_relative_resources_against_document_base() -> None:
    prepared = prepare_html(
        '<base href="https://cdn.example/assets/"><img src="avatar.png">'
    )

    assert prepared.requirements == frozenset({RenderRequirement.NETWORK})


@pytest.mark.parametrize("ratio", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_raster_options_reject_invalid_device_pixel_ratio(ratio: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        RasterOptions(device_pixel_ratio=ratio)


@pytest.mark.anyio
async def test_prepare_text_uses_shared_template_and_css(tmp_path: Path) -> None:
    css = tmp_path / "text.css"
    css.write_text(".text { color: rebeccapurple; }", encoding="utf-8")

    prepared = await prepare_text("<hello>", css_path=str(css))

    assert "&lt;hello&gt;" in prepared.html
    assert any(
        ".text { color: rebeccapurple; }" in stylesheet.css
        for stylesheet in prepared.stylesheets
    )
    assert prepared.base_url is None
    assert prepared.stylesheets[0].base_url == css.resolve().as_uri()


@pytest.mark.anyio
async def test_prepare_markdown_reads_source_and_marks_math_as_javascript(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.md"
    source.write_text("# Title\n\n$$x^2$$", encoding="utf-8")

    prepared = await prepare_markdown(markdown_path=str(source))

    assert "<h1>Title</h1>" in prepared.html
    assert "<script defer>" in prepared.html
    assert RenderRequirement.JAVASCRIPT in prepared.requirements
    assert any(".katex" in stylesheet.css for stylesheet in prepared.stylesheets)


@pytest.mark.anyio
async def test_prepare_template_keeps_directory_base_and_filters(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    (template_root / "card.html").write_text(
        "<strong>{{ name|caps }}</strong>",
        encoding="utf-8",
    )

    prepared = await prepare_template(
        template_root,
        "card.html",
        {"name": "takumi"},
        filters={"caps": str.upper},
    )

    assert prepared.html == "<strong>TAKUMI</strong>"
    assert prepared.base_url == f"{template_root.resolve().as_uri()}/"
