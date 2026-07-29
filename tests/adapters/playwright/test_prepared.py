from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.adapters.playwright.prepared import (
    build_browser_load_plan,
    install_browser_asset_routes,
    materialize_prepared_html,
)
from nonebot_plugin_htmlrender.adapters.resources.reader import (
    AnyioWorkerExecutor,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    PreparedStylesheet,
    prepare_html,
)
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Page
    from pytest_mock import MockerFixture


def _asset_url(payload: bytes) -> str:
    return (
        f"https://htmlrender.invalid/.htmlrender/assets/{sha256(payload).hexdigest()}"
    )


def _resources() -> ResourceService:
    return ResourceService(
        reader=CompositeResourceReader(
            AnyioWorkerExecutor(),
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(allowed_roots=(), allow_any=True),
        strategy=ResourceStrategy(),
    )


def _write_recursive_stylesheets(root: Path) -> tuple[Path, Path, Path, Path]:
    styles = root / "styles"
    styles.mkdir()
    document = root / "document.html"
    site = styles / "site.css"
    theme = styles / "theme.css"
    font = styles / "font.woff2"
    site.write_text('@import "theme.css";', encoding="utf-8")
    theme.write_text('@font-face { src: url("font.woff2") }', encoding="utf-8")
    font.write_bytes(b"font")
    return document, site, theme, font


def test_materialize_prepared_html_preserves_styles_and_routes_assets() -> None:
    prepared = prepare_html(
        """<!doctype html><html><head>
        <style media="screen">.base { background: url(memory:background) }</style>
        </head><body><img src="memory:avatar"></body></html>""",
        stylesheets=(".explicit { mask-image: url('memory:avatar') }",),
        assets=(
            PreparedAsset("memory:avatar", b"avatar", "image/png"),
            PreparedAsset("memory:background", b"background", "image/webp"),
        ),
    )

    document = materialize_prepared_html(prepared)

    assert ".explicit {" in document
    assert '<style media="screen">.base {' in document
    assert "memory:avatar" not in document
    assert "memory:background" not in document
    assert _asset_url(b"avatar") in document
    assert _asset_url(b"background") in document
    assert document.index(".explicit {") < document.index(".base {")


def test_browser_load_plan_rewrites_only_real_tokens() -> None:
    prepared = prepare_html(
        """<html><head><style>@import "memory:second";
        /* url(memory:first) */</style></head><body>
        <!-- <img src="memory:first"> -->
        <script>const sample = '<img src="memory:first">';</script>
        <img srcset="memory:first 1x, memory:second 2x"
             style="background: url(memory:first)">
        </body></html>""",
        assets=(
            PreparedAsset("memory:first", b"first", "image/png"),
            PreparedAsset("memory:second", b"second", "image/png"),
        ),
    )

    plan = build_browser_load_plan(prepared)

    assert '<!-- <img src="memory:first"> -->' in plan.html
    assert "const sample = '<img src=\"memory:first\">';" in plan.html
    assert "/* url(memory:first) */" in plan.html
    assert f'@import "{_asset_url(b"second")}"' in plan.html
    assert f"{_asset_url(b'first')} 1x" in plan.html
    assert f"{_asset_url(b'second')} 2x" in plan.html
    assert f"url({_asset_url(b'first')})" in plan.html


def test_browser_load_plan_deduplicates_routes_by_content() -> None:
    prepared = prepare_html(
        '<img src="memory:first"><img src="memory:second">',
        assets=(
            PreparedAsset("memory:first", b"same", "image/png"),
            PreparedAsset("memory:second", b"same", "image/png"),
        ),
    )

    plan = build_browser_load_plan(prepared)

    assert len(plan.asset_routes) == 1
    assert plan.html.count(_asset_url(b"same")) == 2


def test_browser_load_plan_keeps_navigation_and_resource_base_separate() -> None:
    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="https://assets.example/base/",
    )

    plan = build_browser_load_plan(
        prepared,
        document_url="https://document.example/card",
    )

    assert plan.document_url == "https://document.example/card"
    assert plan.base_href == "https://assets.example/base/"
    assert '<base href="https://assets.example/base/">' in plan.html


def test_browser_load_plan_uses_http_document_as_relative_resource_fallback() -> None:
    prepared = prepare_html('<img src="avatar.png">')

    plan = build_browser_load_plan(
        prepared,
        document_url="https://render.example/cards/card.html",
    )

    assert prepared.document_base.preparation_base_url is None
    assert plan.document_url == "https://render.example/cards/card.html"
    assert plan.base_href == "https://render.example/cards/card.html"
    assert '<base href="https://render.example/cards/card.html">' in plan.html


def test_external_stylesheet_references_use_their_own_http_base() -> None:
    prepared = prepare_html(
        "<main>ok</main>",
        base_url="https://document.example/card/",
        stylesheets=(
            PreparedStylesheet(
                css=(
                    '@import "parts/base.css"; '
                    ".hero { background: url(../images/hero.png) }"
                ),
                base_url="https://cdn.example/themes/site.css",
            ),
        ),
    )

    plan = build_browser_load_plan(prepared)

    assert '@import "https://cdn.example/themes/parts/base.css"' in plan.html
    assert "url(https://cdn.example/images/hero.png)" in plan.html
    assert "https://document.example/card/parts/base.css" not in plan.html


def test_browser_load_plan_ignores_fake_head_and_base_tokens() -> None:
    prepared = prepare_html(
        """<!doctype html><!-- <head><base href="https://fake.example/"> -->
        <script>const fake = '<head><base href="https://fake.example/">';</script>
        <html><body>ok</body></html>""",
        base_url="https://assets.example/",
    )

    plan = build_browser_load_plan(prepared)

    assert plan.base_href == "https://assets.example/"
    assert '<base href="https://assets.example/">' in plan.html
    assert plan.html.index("<head>") < plan.html.index("<html>")
    assert '<!-- <head><base href="https://fake.example/"> -->' in plan.html
    assert "const fake = '<head><base href=\"https://fake.example/\">';" in plan.html


def test_browser_load_plan_uses_real_document_base_for_asset_matching() -> None:
    prepared = prepare_html(
        '<html><head><base href="https://cdn.example/card/"></head>'
        '<body><img src="avatar.png"></body></html>',
        base_url="https://document.example/",
        assets=(
            PreparedAsset(
                "https://cdn.example/card/avatar.png",
                b"avatar",
                "image/png",
            ),
        ),
    )

    plan = build_browser_load_plan(prepared)

    assert plan.base_href == "https://cdn.example/card/"
    assert plan.html.count("<base ") == 1
    assert _asset_url(b"avatar") in plan.html


def test_browser_load_plan_canonicalizes_real_relative_document_base() -> None:
    prepared = prepare_html(
        """<html><head>
        <!-- <base href="comment-assets/"> -->
        <style id="before">.before { color: red }</style>
        <base data-owner="document" href='assets/' target="_blank">
        <style id="after">.after { color: blue }</style>
        <script>const fake = '<base href="script-assets/">';</script>
        </head><body><img src="avatar.png"></body></html>""",
        base_url="file:///srv/cards/document.html",
    )

    plan = build_browser_load_plan(prepared, allow_file_base_href=True)

    assert plan.base_href == "file:///srv/cards/assets/"
    assert (
        "<base data-owner=\"document\" href='file:///srv/cards/assets/' "
        'target="_blank">'
    ) in plan.html
    assert '<!-- <base href="comment-assets/"> -->' in plan.html
    assert "const fake = '<base href=\"script-assets/\">';" in plan.html
    assert plan.html.index('id="before"') < plan.html.index('data-owner="document"')
    assert plan.html.index('data-owner="document"') < plan.html.index('id="after"')


def test_browser_load_plan_rejects_content_type_conflicts() -> None:
    prepared = prepare_html(
        '<img src="memory:image">',
        assets=(
            PreparedAsset("memory:image", b"same", "image/png"),
            PreparedAsset("memory:stylesheet", b"same", "text/css"),
        ),
    )

    with pytest.raises(ValueError, match="conflicting media types"):
        build_browser_load_plan(prepared)


@pytest.mark.anyio
async def test_browser_load_plan_rewrites_recursive_stylesheet_routes(
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.preparation.materialize import (  # noqa: PLC0415
        materialize_local_assets,
    )

    document, site, theme, font = _write_recursive_stylesheets(tmp_path)
    prepared = prepare_html(
        '<link rel="stylesheet" href="styles/site.css">',
        base_url=document.as_uri(),
    )

    plan = build_browser_load_plan(
        await materialize_local_assets(prepared, resources=_resources())
    )
    routes = {route.asset.source: route for route in plan.asset_routes}

    assert site.as_uri() in routes
    assert theme.as_uri() in routes
    assert font.as_uri() in routes
    assert routes[theme.as_uri()].url in routes[site.as_uri()].asset.data.decode()
    assert routes[font.as_uri()].url in routes[theme.as_uri()].asset.data.decode()
    assert routes[site.as_uri()].url in plan.html
    for route in plan.asset_routes:
        assert route.url == _asset_url(route.asset.data)


@pytest.mark.anyio
async def test_install_browser_asset_routes_fulfils_with_cors(
    mocker: MockerFixture,
) -> None:
    asset = PreparedAsset("memory:avatar", b"avatar", "image/png")
    plan = build_browser_load_plan(
        prepare_html('<img src="memory:avatar">', assets=(asset,))
    )
    page = mocker.AsyncMock()

    await install_browser_asset_routes(cast("Page", page), plan)

    page.route.assert_awaited_once_with(
        "https://htmlrender.invalid/.htmlrender/assets/**",
        mocker.ANY,
    )
    handler = page.route.await_args.args[1]
    route = SimpleNamespace(
        request=SimpleNamespace(url=_asset_url(b"avatar")),
        fulfill=mocker.AsyncMock(),
        abort=mocker.AsyncMock(),
    )
    await handler(route)
    route.abort.assert_not_awaited()
    route.fulfill.assert_awaited_once_with(
        status=200,
        body=b"avatar",
        content_type="image/png",
        headers={
            "access-control-allow-origin": "*",
            "cache-control": "public, max-age=31536000, immutable",
        },
    )


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
