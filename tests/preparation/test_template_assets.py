from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer


async def test_template_variables_stage_paths_and_binary_assets(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    (tmp_path / "card.html").write_text(
        '<img src="{{ path }}"><img src="{{ binary }}">'
        '<img src="{{ nested.buffer }}"><img src="{{ duplicate }}">'
    )
    image = tmp_path / "path.png"
    image.write_bytes(b"path-image")
    png = b"\x89PNG\r\n\x1a\nfixture"
    prepared = await preparer.prepare_template(
        tmp_path,
        "card.html",
        {
            "path": image,
            "binary": png,
            "nested": {"buffer": BytesIO(png)},
            "duplicate": bytearray(png),
        },
    )
    assert image.as_uri() in prepared.html
    assert prepared.html.count("memory://htmlrender/template-assets/") == 3
    assert len(prepared.assets) == 1
    assert prepared.assets[0].media_type == "image/png"


async def test_template_binary_media_type_fallback(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    (tmp_path / "card.html").write_text('<object data="{{ payload }}"></object>')
    prepared = await preparer.prepare_template(
        tmp_path,
        "card.html",
        {"payload": b"unknown"},
    )
    assert prepared.assets[0].media_type == "application/octet-stream"


async def test_template_resource_mode_off_does_not_stage_variables(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    (tmp_path / "card.html").write_text("{{ path }}|{{ payload }}")
    outside = tmp_path.parent / "not-authorized.png"

    prepared = await preparer.prepare_template(
        tmp_path,
        "card.html",
        {"path": outside, "payload": b"raw"},
        resource_mode=ResourceResolveMode.OFF,
    )

    assert str(outside) in prepared.html
    assert "b&#39;raw&#39;" in prepared.html
    assert prepared.assets == ()
