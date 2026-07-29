from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.takumi import (
    TakumiImageResource,
    TakumiInputError,
    TakumiResourceError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.adapters.takumi.source import (
    materialize_takumi_document,
    normalize_image_input,
    prepare_takumi_document,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    PreparedStylesheet,
    prepare_html,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)
from tests.adapters.takumi.helpers import resource_service

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_prepared_document_preserves_html_and_stylesheet_order() -> None:
    prepared = prepare_html(
        '<style>.extracted { color: red }</style><img src="memory:avatar">',
        stylesheets=(".explicit { color: blue }",),
        assets=(PreparedAsset("memory:avatar", b"image"),),
    )

    document = prepare_takumi_document(
        prepared,
        stylesheets=(".backend { display: flex }",),
    )

    assert document.html == prepared.html
    assert document.stylesheets == (
        ".explicit { color: blue }",
        ".extracted { color: red }",
        ".backend { display: flex }",
    )
    assert document.images == (TakumiImageResource("memory:avatar", b"image"),)


def test_image_duck_type_does_not_mask_property_errors() -> None:
    class BrokenImage:
        @property
        def src(self) -> str:
            raise KeyError("broken property")

    with pytest.raises(KeyError, match="broken property"):
        normalize_image_input(BrokenImage(), field="image")


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
    assert document.html


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
    with pytest.raises(TakumiResourceError, match="conflicting byte payloads"):
        prepare_takumi_document(prepared, images=[("same", b"explicit")])

    with pytest.raises(TypeError, match="exactly"):
        prepare_takumi_document(
            prepare_html("<div></div>"),
            images=[("key", b"data", "auto")],
        )


def test_document_and_stylesheet_bases_select_only_referenced_assets() -> None:
    prepared = prepare_html(
        '<img src="./avatar.png"><div class="cover"></div>',
        base_url="https://example.test/cards/card.html",
        stylesheets=(
            PreparedStylesheet(
                css=".cover { background-image: url(../images/cover.png) }",
                base_url="https://example.test/css/card.css",
            ),
        ),
        assets=(
            PreparedAsset("https://example.test/cards/avatar.png", b"avatar"),
            PreparedAsset("https://example.test/images/cover.png", b"cover"),
            PreparedAsset("memory:unused", b"unused"),
        ),
    )

    document = prepare_takumi_document(prepared)

    assert [(image.src, image.data) for image in document.images] == [
        ("./avatar.png", b"avatar"),
        ("../images/cover.png", b"cover"),
    ]


def test_canonical_asset_alias_conflicts_are_rejected() -> None:
    prepared = prepare_html(
        '<img src="./avatar.png">',
        base_url="https://example.test/cards/card.html",
        assets=(
            PreparedAsset("./avatar.png", b"one"),
            PreparedAsset("https://example.test/cards/avatar.png", b"two"),
        ),
    )

    with pytest.raises(TakumiResourceError, match="same canonical URL"):
        prepare_takumi_document(prepared)


def test_same_native_key_resolving_to_different_css_assets_is_rejected() -> None:
    prepared = prepare_html(
        "<div></div>",
        stylesheets=(
            PreparedStylesheet(
                ".a { background: url(icon.png) }",
                base_url="https://a.example.test/style.css",
            ),
            PreparedStylesheet(
                ".b { background: url(icon.png) }",
                base_url="https://b.example.test/style.css",
            ),
        ),
        assets=(
            PreparedAsset("https://a.example.test/icon.png", b"a"),
            PreparedAsset("https://b.example.test/icon.png", b"b"),
        ),
    )

    with pytest.raises(TakumiResourceError, match=r"different.*bases"):
        prepare_takumi_document(prepared)


def test_raw_base_href_resolves_document_reference_to_canonical_asset() -> None:
    prepared = prepare_html(
        '<base href="https://cdn.example.test/assets/"><img src="avatar.png">',
        assets=(
            PreparedAsset("https://cdn.example.test/assets/avatar.png", b"avatar"),
        ),
    )

    document = prepare_takumi_document(prepared)

    assert document.images == (TakumiImageResource("avatar.png", b"avatar"),)


@pytest.mark.anyio
async def test_explicit_images_satisfy_materialization_before_local_io(
    tmp_path: Path,
) -> None:
    prepared = prepare_html(
        '<img src="provided.png"><img src="memory:avatar">',
        base_url=(tmp_path / "document.html").as_uri(),
    )

    document = await materialize_takumi_document(
        prepared,
        resources=resource_service(),
        images=(
            TakumiImageResource("provided.png", b"relative"),
            TakumiImageResource("memory:avatar", b"memory"),
        ),
    )

    assert document.images == (
        TakumiImageResource("provided.png", b"relative"),
        TakumiImageResource("memory:avatar", b"memory"),
    )


@pytest.mark.anyio
async def test_resolve_mode_off_skips_local_materialization(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.takumi import source  # noqa: PLC0415

    prepared = prepare_html(
        '<img src="missing.png">',
        base_url=(tmp_path / "document.html").as_uri(),
    )
    materialize = mocker.patch.object(
        source,
        "materialize_local_assets",
        new=mocker.AsyncMock(),
    )

    document = await materialize_takumi_document(
        prepared,
        resources=resource_service(
            strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.OFF)
        ),
    )

    assert document.images == ()
    materialize.assert_not_awaited()


@pytest.mark.anyio
async def test_auto_tolerates_but_strict_rejects_missing_local_resource(
    tmp_path: Path,
) -> None:
    prepared = prepare_html(
        '<img src="missing.png">',
        base_url=(tmp_path / "document.html").as_uri(),
    )

    automatic = await materialize_takumi_document(
        prepared,
        resources=resource_service(
            strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.AUTO)
        ),
    )

    assert automatic.images == ()
    with pytest.raises(TakumiResourceError, match=r"missing\.png"):
        await materialize_takumi_document(
            prepared,
            resources=resource_service(
                strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.STRICT)
            ),
        )


def test_adapter_upstream_tuple_and_promised_duck_images_are_supported() -> None:
    from takumi_py import ImageResource  # noqa: PLC0415

    @dataclass(frozen=True)
    class PromisedImage:
        src: str
        data: bytes
        cache: str = "none"

    prepared = prepare_html(
        '<img src="adapter"><img src="upstream"><img src="tuple"><img src="duck">'
    )
    document = prepare_takumi_document(
        prepared,
        images=(
            TakumiImageResource("adapter", b"a"),
            ImageResource("upstream", b"b", cache="none"),
            ("tuple", b"c"),
            PromisedImage("duck", b"d"),
            TakumiImageResource("unused", b"e"),
        ),
    )

    assert [(image.src, image.data, image.cache) for image in document.images] == [
        ("adapter", b"a", "auto"),
        ("upstream", b"b", "none"),
        ("tuple", b"c", "auto"),
        ("duck", b"d", "none"),
    ]


def test_media_condition_is_rejected_instead_of_becoming_unconditional() -> None:
    prepared = prepare_html(
        "<div>print only</div>",
        stylesheets=(
            PreparedStylesheet(
                css="div { display: none }",
                media="print",
            ),
        ),
    )

    with pytest.raises(TakumiUnsupportedError, match=r"media='print'"):
        prepare_takumi_document(prepared)

    embedded = prepare_html(
        '<style media="screen and (min-width: 1px)">div { color: red }</style>'
        "<div>conditional</div>"
    )
    with pytest.raises(TakumiUnsupportedError, match="cannot be represented"):
        prepare_takumi_document(embedded)


def test_token_aware_rejection_ignores_html_and_css_text_lookalikes() -> None:
    prepared = prepare_html(
        "<!-- <link rel='stylesheet' href='ignored.css'> -->"
        "<div>&lt;link rel='stylesheet' href='also-ignored.css'&gt;</div>",
        stylesheets=(
            PreparedStylesheet(
                "/* @import 'ignored.css'; @font-face {} */"
                'div::before { content: "@import @font-face"; }'
                'div { background: url("data:image/svg+xml,@import"); }'
            ),
        ),
    )

    document = prepare_takumi_document(prepared)

    assert document.html == prepared.html


@pytest.mark.parametrize(
    ("prepared", "images", "field"),
    [
        (prepare_html("<div>\ud800</div>"), None, "prepared.html"),
        (
            prepare_html(
                "<div></div>",
                stylesheets=(PreparedStylesheet("div { content: '\ud800' }"),),
            ),
            None,
            "stylesheets[0].css",
        ),
        (
            prepare_html('<img src="image">'),
            (TakumiImageResource("\ud800", b"data"),),
            "images[0].src",
        ),
    ],
)
def test_unencodable_strings_are_rejected_with_field_context(
    prepared,
    images,
    field: str,
) -> None:
    with pytest.raises(TakumiInputError) as exc_info:
        prepare_takumi_document(prepared, images=images)

    assert exc_info.value.field == field
