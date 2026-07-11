from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from pytest_mock import MockerFixture


@dataclass(slots=True)
class _SessionStub:
    mode: str
    handle: object = field(default_factory=object)


def _write_font_stylesheet(root: Path) -> Path:
    stylesheet = root / "site.css"
    stylesheet.write_text(
        '@font-face { src: url("font.woff2") }',
        encoding="utf-8",
    )
    return stylesheet


def test_page_config_migrates_deprecated_base_url() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        PageConfig,
        RenderConfig,
    )

    with pytest.warns(DeprecationWarning, match="base_url is deprecated"):
        page = PageConfig(base_url="https://render/document")
    assert page.base_url == "https://render/document"
    assert page.document_url == "https://render/document"
    page_dump = page.model_dump()
    assert page_dump["document_url"] == "https://render/document"
    assert "base_url" not in page_dump
    assert PageConfig.model_validate(page_dump) == page

    render = RenderConfig(page=page)
    restored_render = RenderConfig.model_validate_json(render.model_dump_json())
    assert restored_render == render
    assert restored_render.page.base_url == "https://render/document"

    with pytest.raises(ValueError, match="provide only document_url"):
        PageConfig(
            base_url="https://legacy.example/document",
            document_url="https://new.example/document",
        )

    assigned = PageConfig()
    with pytest.warns(DeprecationWarning, match="base_url is deprecated"):
        assigned.base_url = "https://assigned.example/document"
    assert assigned.base_url == "https://assigned.example/document"
    assert assigned.document_url == "https://assigned.example/document"


@pytest.mark.anyio
async def test_remote_http_navigation_is_resource_fallback_for_both_url_fields(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        operations,
    )
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    document_url = "https://render.example/cards/card.html"
    direct = PageConfig(document_url=document_url)
    with pytest.warns(DeprecationWarning, match="base_url is deprecated"):
        legacy = PageConfig(base_url=document_url)
    execute = mocker.patch.object(
        operations,
        "_execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    mocker.patch.object(
        operations,
        "get_playwright_config",
        return_value=SimpleNamespace(
            remote_local_resource_policy="memory",
            local_local_resource_policy="file",
        ),
    )
    prepared = prepare_html('<img src="avatar.png">')

    for page in (direct, legacy):
        assert (
            await operations.render_prepared_html(
                prepared,
                content=ContentConfig(html=prepared.html),
                render=RenderConfig(page=page),
                session=_SessionStub(mode="remote_ws"),
                strict_assets=True,
            )
            == b"image"
        )

    assert execute.await_count == 2
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
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
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
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=context_manager,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="memory"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=render,
        session=_SessionStub(mode="remote_ws"),
        strict_assets=True,
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
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url="file:///shared/card/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="passthrough"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(
            page=PageConfig(document_url="file:///shared/card/document.html")
        ),
        session=_SessionStub(mode="remote_ws"),
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
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<head><base href="assets/"></head><img src="avatar.png">',
        base_url="file:///shared/cards/document.html",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=SimpleNamespace(
            remote_local_resource_policy="passthrough",
            local_local_resource_policy="file",
        ),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(page=PageConfig()),
        session=_SessionStub(mode=mode),
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
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
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
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"unexpected"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="error"),
    )

    with pytest.raises(AssetMaterializationError, match="not allowed"):
        await render_prepared_html(
            prepared,
            content=ContentConfig(html=prepared.html),
            render=RenderConfig(),
            session=_SessionStub(mode="remote_ws"),
            strict_assets=False,
        )

    execute.assert_not_awaited()


@pytest.mark.anyio
async def test_remote_error_policy_accepts_http_fallback_with_relative_base(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    prepared = prepare_html(
        '<base href="assets/"><img src="avatar.png">',
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="error"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(
            page=PageConfig(document_url="https://render.example/cards/card.html")
        ),
        session=_SessionStub(mode="remote_ws"),
        strict_assets=True,
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
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_html  # noqa: PLC0415

    (tmp_path / "avatar.png").write_bytes(b"avatar")
    prepared = prepare_html(
        '<img src="avatar.png">',
        base_url=f"{tmp_path.as_uri().rstrip('/')}/",
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    publish = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_filehost_url",
        new=mocker.AsyncMock(return_value="http://filehost/filehost/avatar"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="filehost"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.create_filehost_lease",
        return_value="lease",
    )
    release = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.release_filehost_lease",
        new=mocker.AsyncMock(),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        session=_SessionStub(mode="remote_ws"),
        strict_assets=True,
    )

    assert result == b"image"
    publish.assert_awaited_once_with(
        b"avatar",
        lease_id="lease",
        suffix=".png",
    )
    release.assert_awaited_once_with("lease")
    call = execute.await_args
    assert call is not None
    plan = call.args[0]
    assert "http://filehost/filehost/avatar" in plan.html
    assert plan.asset_routes == ()


@pytest.mark.anyio
async def test_filehost_render_releases_owned_lease_under_cancellation(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        operations,
    )
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
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

    mocker.patch.object(
        operations,
        "get_playwright_config",
        return_value=SimpleNamespace(remote_local_resource_policy="filehost"),
    )
    mocker.patch.object(operations, "create_filehost_lease", return_value="lease")
    mocker.patch.object(
        operations,
        "resolve_filehost_url",
        new=mocker.AsyncMock(return_value="https://filehost.example/avatar.png"),
    )
    mocker.patch.object(operations, "_execute_browser_load_plan", side_effect=execute)
    release = mocker.patch.object(
        operations,
        "release_filehost_lease",
        new=mocker.AsyncMock(),
    )

    async def render() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await operations.render_prepared_html(
                prepared,
                content=ContentConfig(html=prepared.html),
                render=RenderConfig(),
                session=_SessionStub(mode="remote_ws"),
            )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await started.wait()
        if owner_scope is None:
            raise RuntimeError("render cancellation scope was not initialized")
        owner_scope.cancel()

    release.assert_awaited_once_with("lease")


@pytest.mark.anyio
async def test_filehost_asset_graph_preserves_css_and_font_suffixes(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
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
    ) -> str:
        assert lease_id == "lease"
        return f"http://filehost/filehost/{len(payload)}{suffix or ''}"

    publish_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_filehost_url",
        new=mocker.AsyncMock(side_effect=publish),
    )

    urls = await _publish_prepared_assets(prepared, lease_id="lease")

    assert urls[font.source].endswith(".woff2")
    assert urls[stylesheet.source].endswith(".css")
    calls = publish_mock.await_args_list
    assert calls[0].kwargs["suffix"] == ".woff2"
    assert calls[1].kwargs["suffix"] == ".css"
    assert urls[font.source].encode() in calls[1].args[0]


@pytest.mark.anyio
async def test_local_file_policy_keeps_stylesheet_io_in_browser(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )
    from nonebot_plugin_htmlrender.preparation import prepare_text  # noqa: PLC0415

    stylesheet = _write_font_stylesheet(tmp_path)
    prepared = await prepare_text(
        "ok",
        css_path=str(stylesheet),
    )
    execute = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations._execute_browser_load_plan",
        new=mocker.AsyncMock(return_value=b"image"),
    )
    materialize = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.materialize_local_assets",
        new=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(local_local_resource_policy="file"),
    )

    result = await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=RenderConfig(),
        session=_SessionStub(mode="local_pw"),
    )

    assert result == b"image"
    materialize.assert_not_awaited()
    call = execute.await_args
    assert call is not None
    plan = call.args[0]
    assert (tmp_path / "font.woff2").as_uri() in plan.html
    assert "https://htmlrender.invalid" not in plan.html


def test_should_attach_filehost_header_only_for_local_filehost_urls() -> None:
    from nonebot_plugin_htmlrender.backend.playwright._page import (  # noqa: PLC0415
        _should_attach_filehost_header,
    )

    assert _should_attach_filehost_header("http://render:9012/filehost/abc") is True
    assert _should_attach_filehost_header("https://localhost/filehost/abc") is True
    assert _should_attach_filehost_header("https://example.com/filehost/abc") is False
    assert _should_attach_filehost_header("http://render:9012/assets/abc") is False


@pytest.mark.anyio
async def test_install_filehost_request_route_injects_header_selectively(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright._page import (  # noqa: PLC0415
        install_filehost_request_route as _install_filehost_request_route,
    )

    page = mocker.AsyncMock()

    await _install_filehost_request_route(
        page,
        filehost_headers={"X-HTMLRender-Filehost-Request": "unit-token"},
    )

    page.route.assert_awaited_once()
    route_handler = page.route.await_args.args[1]

    filehost_route = SimpleNamespace(
        request=SimpleNamespace(
            url="http://render:9012/filehost/abc",
            headers={"user-agent": "pw"},
        ),
        continue_=mocker.AsyncMock(),
    )
    await route_handler(filehost_route)
    filehost_route.continue_.assert_awaited_once()
    continued_headers = filehost_route.continue_.await_args.kwargs["headers"]
    assert continued_headers["X-HTMLRender-Filehost-Request"] == "unit-token"

    external_route = SimpleNamespace(
        request=SimpleNamespace(
            url="https://example.com/filehost/abc",
            headers={"user-agent": "pw"},
        ),
        continue_=mocker.AsyncMock(),
    )
    await route_handler(external_route)
    external_route.continue_.assert_awaited_once_with()


def test_operations_redact_url_masks_credentials_and_query() -> None:
    from nonebot_plugin_htmlrender.backend.playwright._page import (  # noqa: PLC0415
        _redact_url,
    )

    redacted = _redact_url("https://user:pass@example.com:8443/path?a=1#x")
    assert redacted == "https://example.com:8443/path"


@pytest.mark.anyio
async def test_capture_html_element_uses_direct_operation_api(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        capture_html_element,
    )

    page = mocker.AsyncMock()
    page.on = mocker.MagicMock()
    locator = mocker.AsyncMock()
    locator.screenshot.return_value = b"element-image"
    page.locator = mocker.MagicMock(return_value=locator)

    context_manager = mocker.MagicMock()
    context_manager.__aenter__ = mocker.AsyncMock(return_value=page)
    context_manager.__aexit__ = mocker.AsyncMock(return_value=None)

    open_page_context_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=context_manager,
    )
    log_telemetry_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )

    result = await capture_html_element(
        "https://example.com",
        "#target",
        page_kwargs={"device_scale_factor": 2.0},
        goto_kwargs={"timeout": 4_000},
        screenshot_kwargs={"type": "jpeg", "quality": 80},
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"element-image"
    assert open_page_context_mock.call_count == 1
    assert open_page_context_mock.call_args.kwargs["session"] is not None
    assert open_page_context_mock.call_args.kwargs["device_scale_factor"] == 2.0
    page.goto.assert_awaited_once_with("https://example.com", timeout=4_000)
    page.locator.assert_called_once_with("#target")
    locator.screenshot.assert_awaited_once_with(type="jpeg", quality=80)
    log_telemetry_mock.assert_awaited_once_with(
        page,
        op="playwright.html_render.capture_html_element",
    )


def test_registered_render_context_provider_errors_without_registration() -> None:
    from nonebot_plugin_htmlrender.backend.playwright import _page  # noqa: PLC0415

    original = _page._render_context_state["provider"]
    _page._render_context_state["provider"] = None
    try:
        with pytest.raises(
            RuntimeError, match="No render context provider is registered"
        ):
            _page._get_registered_render_context()
    finally:
        _page._render_context_state["provider"] = original


@pytest.mark.anyio
async def test_open_page_context_provider_and_session_paths(
    mocker: MockerFixture,
) -> None:
    from contextlib import asynccontextmanager  # noqa: PLC0415

    from nonebot_plugin_htmlrender.backend.playwright import _page  # noqa: PLC0415

    @asynccontextmanager
    async def _provider(**kwargs: object):  # noqa: ARG001
        yield object()

    mocker.patch.object(_page, "_as_page", side_effect=lambda page: page)
    _page.register_render_context_provider(_provider)
    async with _page.open_page_context() as page:
        assert page is not None

    from playwright.async_api import Browser  # noqa: PLC0415

    page = mocker.AsyncMock()
    browser = mocker.AsyncMock(spec=Browser)
    browser.new_page.return_value = page
    instrument = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright._page.instrument_page"
    )
    detach = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright._page.detach_page"
    )
    session = SimpleNamespace(handle=browser)
    async with _page.open_page_context(
        session=session,  # pyright: ignore[reportArgumentType]
        viewport={"width": 1, "height": 1},
    ) as page2:
        assert page2 is page
    instrument.assert_called_once()
    detach.assert_called_once_with(page)


@pytest.mark.anyio
async def test_open_page_context_detaches_telemetry_on_error_and_cancellation(
    mocker: MockerFixture,
) -> None:
    from playwright.async_api import Browser  # noqa: PLC0415

    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        _page,
        telemetry,
    )

    telemetry._collectors.clear()
    error_page = mocker.AsyncMock()
    error_page.on = mocker.MagicMock()
    error_browser = mocker.AsyncMock(spec=Browser)
    error_browser.new_page.return_value = error_page
    error_session = _SessionStub(mode="local_pw", handle=error_browser)

    with pytest.raises(RuntimeError, match="render failed"):
        async with _page.open_page_context(session=error_session) as opened:
            assert telemetry.get_page_collector(opened) is not None
            raise RuntimeError("render failed")
    assert telemetry.get_page_collector(error_page) is None
    error_page.close.assert_awaited_once_with()

    cancelled_page = mocker.AsyncMock()
    cancelled_page.on = mocker.MagicMock()
    cancelled_browser = mocker.AsyncMock(spec=Browser)
    cancelled_browser.new_page.return_value = cancelled_page
    cancelled_session = _SessionStub(mode="local_pw", handle=cancelled_browser)
    started = anyio.Event()
    owner_scope: anyio.CancelScope | None = None

    async def hold_page() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            async with _page.open_page_context(session=cancelled_session) as opened:
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


def test_operation_helpers_misc_branches(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        _page,
        operations,
    )

    assert _page._iter_http_urls({"a": ("http://x", {"b": {"https://y"}})}) == [
        "http://x",
        "https://y",
    ]
    assert _page._is_local_or_private_target("http://localhost/a") is True
    assert _page._is_local_or_private_target("mailto:a@b.com") is False
    assert operations._enum_value(SimpleNamespace(value="x")) == "x"
    assert operations._enum_value("y") == "y"

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright._page.urlsplit",
        side_effect=RuntimeError,
    )
    assert _page._redact_url("??") == "??"


@pytest.mark.anyio
async def test_install_filehost_request_route_no_headers_is_noop(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright._page import (  # noqa: PLC0415
        install_filehost_request_route,
    )

    page = mocker.AsyncMock()
    await install_filehost_request_route(page, filehost_headers={})
    page.route.assert_not_awaited()
