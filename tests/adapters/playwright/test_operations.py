from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import anyio
import pytest

from nonebot_plugin_htmlrender.adapters.resources.reader import (
    AnyioWorkerExecutor,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
)
from nonebot_plugin_htmlrender.resources.config import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.models import PublishedResource
from nonebot_plugin_htmlrender.resources.service import ResourceService


def _published(url: str, headers: dict[str, str] | None = None) -> PublishedResource:
    return PublishedResource(url=url, request_headers=headers or {})


if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease


@dataclass(slots=True)
class _LeaseStub:
    mode: str
    browser: object = field(default_factory=object)


def _lease(mode: str, *, browser: object | None = None) -> PlaywrightLease:
    return cast(
        "PlaywrightLease",
        _LeaseStub(mode=mode, browser=object() if browser is None else browser),
    )


def _resources(
    *,
    remote_policy: RemoteLocalResourcePolicy = RemoteLocalResourcePolicy.MEMORY,
    local_policy: LocalLocalResourcePolicy = LocalLocalResourcePolicy.FILE,
    resolve_mode: ResourceResolveMode = ResourceResolveMode.AUTO,
) -> ResourceService:
    return ResourceService(
        reader=CompositeResourceReader(
            AnyioWorkerExecutor(),
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(allowed_roots=(), allow_any=True),
        strategy=ResourceStrategy(
            resolve_mode=resolve_mode,
            remote_local_policy=remote_policy,
            local_local_policy=local_policy,
        ),
    )


def _write_font_stylesheet(root: Path) -> Path:
    stylesheet = root / "site.css"
    stylesheet.write_text(
        '@font-face { src: url("font.woff2") }',
        encoding="utf-8",
    )
    return stylesheet


def test_page_config_roundtrips_document_url() -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        PageConfig,
        RenderConfig,
    )

    page = PageConfig(document_url="https://render/document")
    assert page.document_url == "https://render/document"
    page_dump = page.model_dump()
    assert page_dump["document_url"] == "https://render/document"
    assert "base_url" not in page_dump
    assert PageConfig.model_validate(page_dump) == page

    render = RenderConfig(page=page)
    restored_render = RenderConfig.model_validate_json(render.model_dump_json())
    assert restored_render == render
    assert restored_render.page.document_url == "https://render/document"


@pytest.mark.anyio
async def test_remote_http_navigation_is_resource_fallback(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import (  # noqa: PLC0415
        operations,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    document_url = "https://render.example/cards/card.html"
    page = PageConfig(document_url=document_url)
    execute = mocker.patch.object(
        operations,
        "_execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    resources = _resources()
    prepared = prepare_html('<img src="avatar.png">')

    assert (
        await operations.render_prepared_html(
            prepared,
            content=ContentConfig(html=prepared.html),
            render=RenderConfig(page=page),
            lease=_lease("remote_ws"),
            resources=resources,
            asset_publisher=None,
            resolve_mode=ResourceResolveMode.STRICT,
        )
        == b"image"
    )

    assert execute.await_count == 1
    for call in execute.await_args_list:
        plan = call.args[0]
        assert plan.document_url == document_url
        assert plan.base_href == document_url
        assert '<base href="https://render.example/cards/card.html">' in plan.html


@pytest.mark.anyio
async def test_remote_prepared_render_routes_local_assets_without_file_navigation(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    (tmp_path / "avatar.png").write_bytes(b"avatar")
    base_url = f"{tmp_path.as_uri().rstrip('/')}/"
    prepared = prepare_html('<img src="avatar.png">', base_url=base_url)
    render = RenderConfig(page=PageConfig())
    page = mocker.AsyncMock()
    page.on = mocker.MagicMock()
    page.screenshot = mocker.AsyncMock(return_value=b"image")
    context_manager = mocker.MagicMock()
    context_manager.__aenter__ = mocker.AsyncMock(return_value=page)
    context_manager.__aexit__ = mocker.AsyncMock(return_value=None)
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.PageContext.open",
        return_value=context_manager,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=render,
        lease=_lease("remote_ws"),
        resources=_resources(),
        asset_publisher=None,
        resolve_mode=ResourceResolveMode.STRICT,
    )

    assert result == b"image"
    page.goto.assert_not_awaited()
    injected = page.set_content.await_args.args[0]
    assert "file://" not in injected
    assert "https://htmlrender.invalid/.htmlrender/assets/" in injected
    page.route.assert_awaited_once()


@pytest.mark.anyio
async def test_remote_passthrough_preserves_shared_file_navigation(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="file:///shared/card/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(
            page=PageConfig(document_url="file:///shared/card/document.html")
        ),
        lease=_lease("remote_ws"),
        resources=_resources(remote_policy=RemoteLocalResourcePolicy.PASSTHROUGH),
        asset_publisher=None,
    )

    assert result == b"image"
    call = execute.await_args
    assert call is not None
    plan = call.args[0]
    assert plan.document_url == "file:///shared/card/document.html"
    assert plan.base_href == "file:///shared/card/"
    assert "avatar.png" in plan.html
    assert plan.asset_routes == ()


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("local_pw", id="local-file"),
        pytest.param("remote_ws", id="remote-passthrough"),
    ],
)
@pytest.mark.anyio
async def test_direct_file_policies_canonicalize_relative_document_base(
    mocker: MockerFixture,
    mode: str,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<head><base href="assets/"></head><img src="avatar.png">',
        base_url="file:///shared/cards/document.html",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    resources = _resources(
        remote_policy=RemoteLocalResourcePolicy.PASSTHROUGH,
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(page=PageConfig()),
        lease=_lease(mode),
        resources=resources,
        asset_publisher=None,
    )

    assert result == b"image"
    assert execute.await_args is not None
    plan = execute.await_args.args[0]
    assert plan.document_url is None
    assert plan.base_href == "file:///shared/cards/assets/"
    assert '<base href="file:///shared/cards/assets/">' in plan.html
    assert 'src="avatar.png"' in plan.html
    assert plan.asset_routes == ()


@pytest.mark.anyio
async def test_remote_error_policy_rejects_local_resources_before_page_open(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415
    from nonebot_plugin_htmlrender.preparation.materialize import (  # noqa: PLC0415
        AssetMaterializationError,
    )

    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="file:///private/card/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"unexpected"),
    )

    with pytest.raises(AssetMaterializationError, match="not allowed"):
        await render_prepared_html(
            prepared,
            content=ContentConfig(html=prepared.html),
            render=RenderConfig(),
            lease=_lease("remote_ws"),
            resources=_resources(remote_policy=RemoteLocalResourcePolicy.ERROR),
            asset_publisher=None,
            resolve_mode=ResourceResolveMode.AUTO,
        )

    execute.assert_not_awaited()


@pytest.mark.anyio
async def test_remote_error_policy_accepts_http_fallback_with_relative_base(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<base href="assets/"><img src="avatar.png">',
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(
            page=PageConfig(document_url="https://render.example/cards/card.html")
        ),
        lease=_lease("remote_ws"),
        resources=_resources(remote_policy=RemoteLocalResourcePolicy.ERROR),
        asset_publisher=None,
        resolve_mode=ResourceResolveMode.STRICT,
    )

    assert result == b"image"
    assert execute.await_args is not None
    plan = execute.await_args.args[0]
    assert plan.base_href == "https://render.example/cards/assets/"


@pytest.mark.anyio
async def test_remote_filehost_policy_publishes_materialized_assets(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    (tmp_path / "avatar.png").write_bytes(b"avatar")
    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url=f"{tmp_path.as_uri().rstrip('/')}/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    publisher = mocker.Mock()
    publisher.create_lease.return_value = "lease"
    publisher.publish = mocker.AsyncMock(
        return_value=_published(
            "http://filehost/filehost/avatar",
            {"X-HTMLRender-Filehost-Request": "unit-token"},
        )
    )
    publisher.release = mocker.AsyncMock()

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        lease=_lease("remote_ws"),
        resources=_resources(
            remote_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        asset_publisher=publisher,
        resolve_mode=ResourceResolveMode.STRICT,
    )

    assert result == b"image"
    publisher.publish.assert_awaited_once_with(
        b"avatar",
        lease_id="lease",
        suffix=".png",
    )
    publisher.release.assert_awaited_once_with("lease")
    call = execute.await_args
    assert call is not None
    plan = call.args[0]
    assert "http://filehost/filehost/avatar" in plan.html
    assert plan.asset_routes == ()


@pytest.mark.anyio
async def test_resolve_mode_off_bypasses_filehost_without_a_publisher(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="file:///shared/card/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        lease=_lease("remote_ws"),
        resources=_resources(
            remote_policy=RemoteLocalResourcePolicy.FILEHOST,
            resolve_mode=ResourceResolveMode.OFF,
        ),
        asset_publisher=None,
    )

    assert result == b"image"
    assert execute.await_args is not None
    plan = execute.await_args.args[0]
    assert plan.base_href == "file:///shared/card/"
    assert plan.asset_routes == ()
    assert execute.await_args.kwargs["local_resource_policy"] == "passthrough"


@pytest.mark.anyio
async def test_per_call_off_does_not_touch_composed_filehost_publisher(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="file:///shared/card/",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    publisher = mocker.Mock()

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        lease=_lease("remote_ws"),
        resources=_resources(remote_policy=RemoteLocalResourcePolicy.FILEHOST),
        asset_publisher=publisher,
        resolve_mode=ResourceResolveMode.OFF,
    )

    assert result == b"image"
    assert publisher.mock_calls == []


@pytest.mark.anyio
async def test_filehost_render_releases_owned_lease_under_cancellation(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import (  # noqa: PLC0415
        operations,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.preparation import (  # noqa: PLC0415
        PreparedAsset,
        prepare_html,
    )

    prepared = prepare_html(
        '<img src="memory:avatar">',
        assets=(PreparedAsset("memory:avatar", b"avatar", "image/png"),),
    )
    started = anyio.Event()
    owner_scope: anyio.CancelScope | None = None

    async def execute(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        started.set()
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    publisher = mocker.Mock()
    publisher.create_lease.return_value = "lease"
    publisher.publish = mocker.AsyncMock(
        return_value=_published("https://filehost.example/avatar.png")
    )
    mocker.patch.object(operations, "_execute_browser_load_plan", side_effect=execute)
    publisher.release = mocker.AsyncMock()

    async def render() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await operations.render_prepared_html(
                prepared,
                content=ContentConfig(html=prepared.html),
                render=RenderConfig(),
                lease=_lease("remote_ws"),
                resources=_resources(
                    remote_policy=RemoteLocalResourcePolicy.FILEHOST,
                ),
                asset_publisher=publisher,
            )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await started.wait()
        if owner_scope is None:
            raise RuntimeError("render cancellation scope was not initialized")
        owner_scope.cancel()

    publisher.release.assert_awaited_once_with("lease")


@pytest.mark.anyio
async def test_filehost_asset_graph_preserves_css_and_font_suffixes(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        _publish_prepared_assets,
    )
    from nonebot_plugin_htmlrender.preparation import (  # noqa: PLC0415
        PreparedAsset,
        prepare_html,
    )

    font = PreparedAsset(
        "file:///card/font.woff2",
        b"font",
        "font/woff2",
    )
    stylesheet = PreparedAsset(
        "file:///card/site.css",
        b'@font-face { src: url("font.woff2") }',
        "text/css",
    )
    prepared = prepare_html(
        '<link rel="stylesheet" href="site.css">',
        base_url="file:///card/document.html",
        assets=(stylesheet, font),
    )

    async def publish(
        payload: bytes,
        *,
        lease_id: str,
        suffix: str | None,
    ) -> PublishedResource:
        assert lease_id == "lease"
        return _published(
            f"http://filehost/filehost/{len(payload)}{suffix or ''}",
            {"X-HTMLRender-Filehost-Request": "unit-token"},
        )

    publisher = mocker.Mock()
    publisher.publish = mocker.AsyncMock(side_effect=publish)

    urls, authorization = await _publish_prepared_assets(
        prepared,
        publisher=publisher,
        lease_id="lease",
    )

    assert urls[font.source].endswith(".woff2")
    assert urls[stylesheet.source].endswith(".css")
    calls = publisher.publish.await_args_list
    assert calls[0].kwargs["suffix"] == ".woff2"
    assert calls[1].kwargs["suffix"] == ".css"
    assert urls[font.source].encode() in calls[1].args[0]
    # Every publication's exact URL carries its own authorization.
    assert set(authorization) == {urls[font.source], urls[stylesheet.source]}
    assert all(
        headers["X-HTMLRender-Filehost-Request"] == "unit-token"
        for headers in authorization.values()
    )


@pytest.mark.anyio
async def test_local_file_policy_keeps_stylesheet_io_in_browser(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import (  # noqa: PLC0415
        PreparedStylesheet,
        prepare_html,
    )

    stylesheet = _write_font_stylesheet(tmp_path)
    prepared = prepare_html(
        "<p>ok</p>",
        stylesheets=(
            PreparedStylesheet(
                css=stylesheet.read_text(encoding="utf-8"),
                base_url=stylesheet.as_uri(),
            ),
        ),
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    materialize = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.materialize_local_assets",
        new=mocker.AsyncMock(),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        lease=_lease("local_pw"),
        resources=_resources(),
        asset_publisher=None,
    )

    assert result == b"image"
    materialize.assert_not_awaited()
    call = execute.await_args
    assert call is not None
    plan = call.args[0]
    assert (tmp_path / "font.woff2").as_uri() in plan.html
    assert "https://htmlrender.invalid" not in plan.html


@pytest.mark.anyio
async def test_install_filehost_request_route_injects_only_on_exact_published_url(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
        install_filehost_request_route as _install_filehost_request_route,
    )

    page = mocker.AsyncMock()
    published = "http://render:9012/filehost/abc?v=1"
    await _install_filehost_request_route(
        page,
        authorization={published: {"X-HTMLRender-Filehost-Request": "unit-token"}},
    )

    page.route.assert_awaited_once()
    route_handler = page.route.await_args.args[1]

    def _route(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            request=SimpleNamespace(url=url, headers={"user-agent": "pw"}),
            continue_=mocker.AsyncMock(),
            fetch=mocker.AsyncMock(return_value="api-response"),
            fulfill=mocker.AsyncMock(),
        )

    # Exact published URL (port/fragment normalized) is fetched with the header
    # and NO redirect following, then fulfilled directly.
    exact = _route("http://render:9012/filehost/abc?v=1#frag")
    await route_handler(exact)
    exact.continue_.assert_not_awaited()
    assert (
        exact.fetch.await_args.kwargs["headers"]["X-HTMLRender-Filehost-Request"]
        == "unit-token"
    )
    assert exact.fetch.await_args.kwargs["max_redirects"] == 0
    exact.fulfill.assert_awaited_once_with(response="api-response")

    # Same path, different query — no authorization, plain continue.
    other_query = _route("http://render:9012/filehost/abc?v=2")
    await route_handler(other_query)
    other_query.fetch.assert_not_awaited()
    other_query.continue_.assert_awaited_once_with()

    # Same path prefix on another origin — no authorization.
    external = _route("https://example.com/filehost/abc?v=1")
    await route_handler(external)
    external.fetch.assert_not_awaited()
    external.continue_.assert_awaited_once_with()

    # Unpublished path on the same origin — no authorization.
    unpublished = _route("http://render:9012/other/abc?v=1")
    await route_handler(unpublished)
    unpublished.fetch.assert_not_awaited()
    unpublished.continue_.assert_awaited_once_with()


@pytest.mark.anyio
async def test_page_context_uses_injected_lease(
    mocker: MockerFixture,
) -> None:
    from playwright.async_api import Browser  # noqa: PLC0415

    from nonebot_plugin_htmlrender.adapters.playwright import _page  # noqa: PLC0415

    page = mocker.AsyncMock()
    browser = mocker.AsyncMock(spec=Browser)
    browser.new_page.return_value = page
    instrument = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright._page.instrument_page"
    )
    detach = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright._page.detach_page"
    )
    lease = _lease("local_pw", browser=browser)
    async with _page.PageContext(lease).open(
        viewport={"width": 1, "height": 1},
    ) as page2:
        assert page2 is page
    instrument.assert_called_once()
    detach.assert_called_once_with(page)


@pytest.mark.anyio
async def test_page_context_detaches_telemetry_on_error_and_cancellation(
    mocker: MockerFixture,
) -> None:
    from playwright.async_api import Browser  # noqa: PLC0415

    from nonebot_plugin_htmlrender.adapters.playwright import (  # noqa: PLC0415
        _page,
        telemetry,
    )

    error_page = mocker.AsyncMock()
    error_page.on = mocker.MagicMock()
    error_browser = mocker.AsyncMock(spec=Browser)
    error_browser.new_page.return_value = error_page
    error_lease = _lease("local_pw", browser=error_browser)

    with pytest.raises(RuntimeError, match="render failed"):
        async with _page.PageContext(error_lease).open() as opened:
            assert telemetry.get_page_collector(opened) is not None
            raise RuntimeError("render failed")
    assert telemetry.get_page_collector(error_page) is None
    error_page.close.assert_awaited_once_with()

    cancelled_page = mocker.AsyncMock()
    cancelled_page.on = mocker.MagicMock()
    cancelled_browser = mocker.AsyncMock(spec=Browser)
    cancelled_browser.new_page.return_value = cancelled_page
    cancelled_lease = _lease("local_pw", browser=cancelled_browser)
    started = anyio.Event()
    owner_scope: anyio.CancelScope | None = None

    async def hold_page() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            async with _page.PageContext(cancelled_lease).open() as opened:
                assert telemetry.get_page_collector(opened) is not None
                started.set()
                await anyio.sleep_forever()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(hold_page)
        await started.wait()
        if owner_scope is None:
            raise RuntimeError("page cancellation scope was not initialized")
        owner_scope.cancel()

    assert telemetry.get_page_collector(cancelled_page) is None
    cancelled_page.close.assert_awaited_once_with()


def test_normalize_request_url_drops_default_port_and_fragment() -> None:
    from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
        _normalize_request_url,
    )

    assert (
        _normalize_request_url("HTTP://Render:80/filehost/a?v=1#frag")
        == "http://render/filehost/a?v=1"
    )
    assert (
        _normalize_request_url("https://render:8443/filehost/a")
        == "https://render:8443/filehost/a"
    )


@pytest.mark.anyio
async def test_install_filehost_request_route_no_authorization_is_noop(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
        install_filehost_request_route,
    )

    page = mocker.AsyncMock()
    await install_filehost_request_route(page, authorization={})
    page.route.assert_not_awaited()
