from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.preparation import prepare_html, prepare_markdown
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_materialize_recurses_through_local_stylesheets(tmp_path: Path) -> None:
    styles = tmp_path / "styles"
    styles.mkdir()
    document = tmp_path / "document.html"
    image = tmp_path / "image.png"
    stylesheet = styles / "site.css"
    imported = styles / "theme.css"
    font = styles / "font.woff2"
    document.write_text("unused", encoding="utf-8")
    image.write_bytes(b"png")
    font.write_bytes(b"font")
    stylesheet.write_text(
        '@import "theme.css"; .hero { background: url(../image.png) }',
        encoding="utf-8",
    )
    imported.write_text(
        '@font-face { src: url("font.woff2") }',
        encoding="utf-8",
    )
    prepared = prepare_html(
        '<link rel="stylesheet" href="styles/site.css"><img src="image.png">',
        base_url=document.as_uri(),
    )

    materialized = await materialize_local_assets(prepared)

    assert {asset.source for asset in materialized.assets} == {
        stylesheet.as_uri(),
        imported.as_uri(),
        image.as_uri(),
        font.as_uri(),
    }
    assert {asset.media_type for asset in materialized.assets} >= {
        "text/css",
        "image/png",
        "font/woff2",
    }


@pytest.mark.anyio
async def test_markdown_and_css_keep_independent_resource_bases(
    tmp_path: Path,
) -> None:
    markdown_dir = tmp_path / "markdown"
    css_dir = tmp_path / "theme"
    markdown_dir.mkdir()
    css_dir.mkdir()
    markdown_path = markdown_dir / "document.md"
    image = markdown_dir / "image.png"
    css_path = css_dir / "theme.css"
    font = css_dir / "font.woff2"
    markdown_path.write_text("![image](image.png)", encoding="utf-8")
    image.write_bytes(b"image")
    css_path.write_text('@font-face { src: url("font.woff2") }', encoding="utf-8")
    font.write_bytes(b"font")

    prepared = await prepare_markdown(
        markdown_path=str(markdown_path),
        css_path=str(css_path),
    )
    materialized = await materialize_local_assets(prepared)

    assert prepared.base_url == markdown_path.as_uri()
    assert prepared.stylesheets[0].base_url == css_path.as_uri()
    assert {asset.source for asset in materialized.assets} == {
        image.as_uri(),
        font.as_uri(),
    }


@pytest.mark.anyio
async def test_relative_memory_resource_is_strict_by_default() -> None:
    prepared = prepare_html('<img src="relative.png">')

    with pytest.raises(AssetMaterializationError, match="has no filesystem base"):
        await materialize_local_assets(prepared)

    assert (await materialize_local_assets(prepared, strict=False)).assets == ()


@pytest.mark.anyio
async def test_http_document_fallback_classifies_relative_resources_as_network() -> (
    None
):
    prepared = prepare_html('<img src="relative.png">')

    materialized = await materialize_local_assets(
        prepared,
        fallback_base_url="https://render.example/cards/card.html",
    )

    assert materialized.base_url is None
    assert materialized.assets == ()


@pytest.mark.anyio
async def test_memory_markdown_exposes_strict_and_non_strict_resource_modes(
    mocker: MockerFixture,
) -> None:
    warning = mocker.patch(
        "nonebot_plugin_htmlrender.preparation.materialize.logger.warning"
    )

    prepared = await prepare_markdown(
        "![relative](relative.png)",
        resource_strict=False,
    )

    assert prepared.assets == ()
    warning.assert_called_once()

    with pytest.raises(AssetMaterializationError, match="has no filesystem base"):
        await prepare_markdown(
            "![relative](relative.png)",
            resource_strict=True,
        )


@pytest.mark.anyio
async def test_document_base_element_resolves_local_assets(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    image = assets / "image.png"
    image.write_bytes(b"image")
    document = tmp_path / "document.html"
    prepared = prepare_html(
        '<base href="assets/"><img src="image.png">',
        base_url=document.as_uri(),
    )

    materialized = await materialize_local_assets(prepared)

    assert [asset.source for asset in materialized.assets] == [image.as_uri()]
