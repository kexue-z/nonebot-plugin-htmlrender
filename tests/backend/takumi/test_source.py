from __future__ import annotations

import pytest

from nonebot_plugin_htmlrender.backend.takumi import (
    TakumiImageResource,
    TakumiResourceError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.backend.takumi.source import (
    prepare_takumi_document,
)
from nonebot_plugin_htmlrender.preparation import PreparedAsset, prepare_html


def test_prepared_document_preserves_shared_markup_and_stylesheet_order() -> None:
    prepared = prepare_html(
        "<style>.extracted { color: red }</style><div>ok</div>",
        stylesheets=(".explicit { color: blue }",),
        assets=(PreparedAsset("memory:avatar", b"image"),),
    )

    document = prepare_takumi_document(
        prepared,
        stylesheets=(".backend { display: flex }",),
    )

    assert document.markup == prepared.markup
    assert document.stylesheets == (
        ".explicit { color: blue }",
        ".extracted { color: red }",
        ".backend { display: flex }",
    )
    assert document.images == (TakumiImageResource("memory:avatar", b"image"),)


@pytest.mark.parametrize(
    "html,images",
    [
        ('<img src="data:image/png;base64,AA==">', None),
        ('<svg><image href="#symbol"></image></svg>', None),
        ('<img src="memory:avatar">', [TakumiImageResource("memory:avatar", b"x")]),
        ('<img src="tuple-key">', [("tuple-key", b"x")]),
    ],
)
def test_image_references_accept_only_materialized_or_inline_sources(
    html: str,
    images: list[object] | None,
) -> None:
    document = prepare_takumi_document(prepare_html(html), images=images)
    assert document.markup


@pytest.mark.parametrize(
    "html,stylesheets,error",
    [
        ("<script>run()</script>", (), TakumiUnsupportedError),
        ('<link rel="stylesheet" href="x.css">', (), TakumiUnsupportedError),
        ('<link rel="stylesheet preload" href="x.css">', (), TakumiUnsupportedError),
        (
            '<link rel="alternate stylesheet" href="x.css">',
            (),
            TakumiUnsupportedError,
        ),
        ("<div></div>", ('@import "x.css";',), TakumiUnsupportedError),
        (
            "<div></div>",
            ("@font-face { src: url(font.woff2) }",),
            TakumiUnsupportedError,
        ),
        ('<img src="https://example.com/x.png">', (), TakumiResourceError),
        (
            '<div style="background:url(./x.png)"></div>',
            (),
            TakumiResourceError,
        ),
        (
            "<div></div>",
            ("div { background: url(memory:missing) }",),
            TakumiResourceError,
        ),
    ],
)
def test_unsupported_browser_or_unresolved_resource_behavior_is_rejected(
    html: str,
    stylesheets: tuple[str, ...],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        prepare_takumi_document(prepare_html(html), stylesheets=stylesheets)


def test_non_resource_anchor_does_not_require_materialization() -> None:
    document = prepare_takumi_document(prepare_html('<a href="relative">link</a>'))
    assert document.images == ()


def test_duplicate_and_malformed_image_resources_are_rejected() -> None:
    prepared = prepare_html(
        '<img src="same">',
        assets=(PreparedAsset("same", b"asset"),),
    )
    with pytest.raises(TakumiResourceError, match="more than once"):
        prepare_takumi_document(prepared, images=[("same", b"explicit")])

    with pytest.raises(TypeError, match="exactly"):
        prepare_takumi_document(
            prepare_html("<div></div>"),
            images=[("key", b"data", "auto")],
        )
