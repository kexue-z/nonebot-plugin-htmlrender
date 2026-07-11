from __future__ import annotations

import pytest

from nonebot_plugin_htmlrender.backend.playwright.prepared import (
    materialize_prepared_html,
)
from nonebot_plugin_htmlrender.preparation import PreparedAsset, prepare_html


def test_materialize_prepared_html_preserves_styles_and_inlines_assets() -> None:
    prepared = prepare_html(
        """<!doctype html><html><head>
        <style>.base { background: url(memory:background) }</style>
        </head><body><img src="memory:avatar"></body></html>""",
        stylesheets=(".explicit { mask-image: url('memory:avatar') }",),
        assets=(
            PreparedAsset("memory:avatar", b"avatar", "image/png"),
            PreparedAsset("memory:background", b"background", "image/webp"),
        ),
    )

    document = materialize_prepared_html(prepared)

    assert ".explicit {" in document
    assert ".base {" in document
    assert "memory:avatar" not in document
    assert "memory:background" not in document
    assert "data:image/png;base64,YXZhdGFy" in document
    assert "data:image/webp;base64,YmFja2dyb3VuZA==" in document
    assert document.index(".explicit {") < document.index(".base {")


def test_materialize_prepared_html_preserves_plain_document() -> None:
    prepared = prepare_html("<main>unchanged</main>")
    assert materialize_prepared_html(prepared) == prepared.html


@pytest.mark.parametrize(
    "assets",
    [
        (
            PreparedAsset("duplicate", b"first"),
            PreparedAsset("duplicate", b"second"),
        ),
        (PreparedAsset("", b"empty"),),
        (PreparedAsset("asset", b"invalid", 'image/png" unsafe'),),
    ],
)
def test_materialize_prepared_html_rejects_invalid_assets(
    assets: tuple[PreparedAsset, ...],
) -> None:
    prepared = prepare_html("<main></main>", assets=assets)
    with pytest.raises(ValueError):
        materialize_prepared_html(prepared)
