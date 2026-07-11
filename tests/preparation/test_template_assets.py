from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.preparation import prepare_template
from nonebot_plugin_htmlrender.preparation.materialize import materialize_local_assets

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.anyio
async def test_template_variables_stage_paths_and_binary_assets(
    tmp_path: Path,
) -> None:
    template = tmp_path / "card.html"
    template.write_text(
        '<img src="{{ path }}"><img src="{{ binary }}">'
        '<img src="{{ nested.buffer }}"><img src="{{ duplicate }}">',
        encoding="utf-8",
    )
    image = tmp_path / "path.png"
    image.write_bytes(b"path-image")
    png = b"\x89PNG\r\n\x1a\nfixture"

    prepared = await prepare_template(
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
    assert prepared.assets[0].data == png
    assert prepared.assets[0].media_type == "image/png"

    materialized = await materialize_local_assets(prepared)
    assert {asset.source for asset in materialized.assets} == {
        prepared.assets[0].source,
        image.as_uri(),
    }


@pytest.mark.anyio
async def test_template_binary_media_type_has_safe_fallback(tmp_path: Path) -> None:
    (tmp_path / "card.html").write_text(
        '<object data="{{ payload }}"></object>',
        encoding="utf-8",
    )

    prepared = await prepare_template(
        tmp_path,
        "card.html",
        {"payload": b"unknown"},
    )

    assert prepared.assets[0].media_type == "application/octet-stream"
