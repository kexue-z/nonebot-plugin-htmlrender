from __future__ import annotations

import pytest

from nonebot_plugin_htmlrender.preparation import PreparedAsset
from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)


def test_asset_index_matches_exact_and_base_canonical_references() -> None:
    asset = PreparedAsset(
        source="images/logo.png", data=b"logo", media_type="image/png"
    )
    index = PreparedAssetIndex(
        (asset,),
        base_url="file:///srv/render/document.html",
    )

    assert index.match("images/logo.png") is asset
    assert index.match("./images/logo.png") is asset
    assert index.match("file:///srv/render/images/logo.png#icon") is asset
    assert index.match("missing.png") is None


def test_asset_index_rejects_exact_and_canonical_collisions() -> None:
    asset = PreparedAsset(source="images/logo.png", data=b"first")

    with pytest.raises(ValueError, match="supplied more than once"):
        PreparedAssetIndex((asset, asset))

    with pytest.raises(ValueError, match="same canonical URL"):
        PreparedAssetIndex(
            (
                asset,
                PreparedAsset(source="./images/logo.png", data=b"second"),
            ),
            base_url="file:///srv/render/document.html",
        )


def test_reference_resolution_only_uses_hierarchical_supported_bases() -> None:
    assert (
        resolve_document_reference("file:///srv/render/document.html", "./logo.png#x")
        == "file:///srv/render/logo.png"
    )
    assert resolve_document_reference("memory:document", "./logo.png") == "./logo.png"
    assert resolve_document_reference(None, "./logo.png") == "./logo.png"
