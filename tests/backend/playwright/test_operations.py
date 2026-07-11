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


def test_build_html_render_request_preserves_page_and_screenshot_options() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        JpegScreenshotOptions,
        _build_html_render_request,
    )

    request = _build_html_render_request(
        "<main>Hello</main>",
        template_path="https://example.com/base",
        image_type="jpeg",
        quality=72,
        device_scale_factor=1.5,
        screenshot_timeout=12_345,
        full_page=False,
        wait=250,
        viewport={"width": 320, "height": 240},
        user_agent="pw-test-agent",
        extra_http_headers={"x-test": "1"},
    )

    assert request.content.html == "<main>Hello</main>"
    assert request.content.additional_wait == 250
    assert request.render.page.viewport.width == 320
    assert request.render.page.viewport.height == 240
    assert request.render.page.base_url == "about:blank"
    assert request.render.page.document_url is None
    assert request.render.page.user_agent == "pw-test-agent"
    assert request.render.page.extra_http_headers == {"x-test": "1"}
    assert isinstance(request.render.screenshot, JpegScreenshotOptions)
    assert request.render.screenshot.quality == 72
    assert request.render.screenshot.device_scale_factor == 1.5
    assert request.render.screenshot.timeout == 12_345
    assert request.render.screenshot.full_page is False
    assert request.render.screenshot.wait_before_screenshot == 250


def test_build_template_render_request_supports_page_overrides(
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        PngScreenshotOptions,
        TemplateRenderRequest,
        _build_template_render_request,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()

    with pytest.warns(DeprecationWarning, match="base_url is deprecated"):
        request = _build_template_render_request(
            str(template_path),
            "card.html",
            template_vars={"name": "Codex"},
            custom_filters={"caps": str.upper},
            pages={
                "viewport": {"width": 480, "height": 360},
                "base_url": "https://example.com/assets",
                "user_agent": "pw-template-agent",
                "extra_http_headers": {"x-template": "ok"},
            },
            image_type="png",
            quality=None,
            device_scale_factor=2.5,
            screenshot_timeout=54_321,
            wait=99,
        )

    assert isinstance(request, TemplateRenderRequest)
    assert request.template.template_path == str(template_path)
    assert request.template.template_name == "card.html"
    assert request.template.template_vars == {"name": "Codex"}
    assert request.template.custom_filters == {"caps": str.upper}
    assert request.render.page.viewport.width == 480
    assert request.render.page.viewport.height == 360
    assert request.render.page.base_url == "https://example.com/assets"
    assert request.render.page.document_url == "https://example.com/assets"
    assert request.render.page.user_agent == "pw-template-agent"
    assert request.render.page.extra_http_headers == {"x-template": "ok"}
    assert isinstance(request.render.screenshot, PngScreenshotOptions)
    assert request.render.screenshot.device_scale_factor == 2.5
    assert request.render.screenshot.timeout == 54_321
    assert request.render.screenshot.wait_before_screenshot == 99


def test_build_template_render_request_uses_default_base_url_when_missing(
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        _build_template_render_request,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()

    request = _build_template_render_request(
        str(template_path),
        "card.html",
        template_vars={},
        custom_filters=None,
        pages=None,
        image_type="png",
        quality=None,
        device_scale_factor=2.0,
        screenshot_timeout=30_000,
        wait=0,
    )

    assert request.render.page.base_url == "about:blank"
    assert request.render.page.document_url is None
    assert request.render.page.viewport.width == 500
    assert request.render.page.viewport.height == 10


@pytest.mark.anyio
async def test_render_html_opens_page_with_render_config(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        HtmlRenderRequest,
        JpegScreenshotOptions,
        PageConfig,
        RenderConfig,
        ViewportConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_html,
    )

    session = object()
    page = mocker.AsyncMock()
    page.on = mocker.MagicMock()
    page.screenshot = mocker.AsyncMock(return_value=b"jpeg-bytes")

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

    request = HtmlRenderRequest(
        content=ContentConfig(
            html="<section>ok</section>",
            wait_until="load",
            additional_wait=150,
        ),
        render=RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(width=640, height=480),
                document_url="https://example.com",
                user_agent="pw-render-agent",
                extra_http_headers={"x-render": "1"},
            ),
            screenshot=JpegScreenshotOptions(
                quality=85,
                device_scale_factor=1.5,
                timeout=9_999,
                full_page=False,
                wait_before_screenshot=45,
            ),
        ),
    )

    result = await render_html(request, session=session)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]

    assert result == b"jpeg-bytes"
    open_page_context_mock.assert_called_once_with(
        session=session,
        viewport={"width": 640, "height": 480},
        device_scale_factor=1.5,
        user_agent="pw-render-agent",
        extra_http_headers={"x-render": "1"},
    )
    page.goto.assert_awaited_once_with("https://example.com")
    injected_html = page.set_content.await_args.args[0]
    assert '<base href="https://example.com">' in injected_html
    assert "<section>ok</section>" in injected_html
    assert page.set_content.await_args.kwargs == {"wait_until": "load"}
    assert page.wait_for_timeout.await_args_list == [
        mocker.call(150),
        mocker.call(45),
    ]
    page.screenshot.assert_awaited_once_with(
        full_page=False,
        type="jpeg",
        quality=85,
        timeout=9_999,
    )
    log_telemetry_mock.assert_awaited_once_with(
        page,
        op="playwright.html_render.render_html",
    )


@pytest.mark.anyio
async def test_legacy_render_html_template_path_is_only_a_resource_base(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_html,
    )

    render_prepared = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"image"),
    )

    result = await render_html(
        '<img src="avatar.png">',
        template_path="file:///bot/templates/card.html",
        session=_SessionStub(mode="remote_ws"),
    )

    assert result == b"image"
    call = render_prepared.await_args
    assert call is not None
    prepared = call.args[0]
    render = call.kwargs["render"]
    assert prepared.base_url == "file:///bot/templates/card.html"
    assert render.page.document_url is None


@pytest.mark.anyio
async def test_render_markdown_skips_file_navigation_for_remote_browser(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_markdown,
    )

    page = mocker.AsyncMock()
    page.on = mocker.MagicMock()
    page.screenshot = mocker.AsyncMock(return_value=b"markdown-image")

    context_manager = mocker.MagicMock()
    context_manager.__aenter__ = mocker.AsyncMock(return_value=page)
    context_manager.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=context_manager,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=False,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(remote_local_resource_policy="memory"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )

    result = await render_markdown(
        "# Remote Markdown",
        session=_SessionStub(mode="remote_ws"),
    )

    assert result == b"markdown-image"
    page.goto.assert_not_awaited()
    page.set_content.assert_awaited_once()
    assert "Remote Markdown" in page.set_content.await_args.args[0]


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
async def test_filehost_template_releases_resolver_lease_under_cancellation(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        operations,
    )

    (tmp_path / "card.html").write_text("{{ payload }}", encoding="utf-8")
    started = anyio.Event()
    owner_scope: anyio.CancelScope | None = None

    async def resolve(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        started.set()
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    mocker.patch.object(
        operations,
        "get_playwright_config",
        return_value=SimpleNamespace(
            resource_resolve_mode="auto",
            remote_local_resource_policy="filehost",
            local_local_resource_policy="file",
        ),
    )
    mocker.patch.object(operations, "resolve_template_vars", side_effect=resolve)
    mocker.patch.object(operations, "register_filehost_resource_root")
    mocker.patch.object(operations, "create_filehost_lease", return_value="lease")
    release = mocker.patch.object(
        operations,
        "release_filehost_lease",
        new=mocker.AsyncMock(),
    )

    async def render() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await operations.render_template(
                str(tmp_path),
                template_name="card.html",
                templates={"payload": b"payload"},
                resource_resolver="auto",
                session=_SessionStub(mode="remote_ws"),
            )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await started.wait()
        if owner_scope is None:
            raise RuntimeError("template cancellation scope was not initialized")
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


@pytest.mark.anyio
async def test_render_text_uses_custom_css_file(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        JpegScreenshotOptions,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_text,
    )

    css_path = tmp_path / "custom.css"
    css_path.write_text("body { color: red; }", encoding="utf-8")

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"text-image"),
    )

    result = await render_text(
        "hello world",
        css_path=str(css_path),
        width=420,
        image_type="jpeg",
        quality=66,
        device_scale_factor=1.25,
        screenshot_timeout=4_321,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"text-image"
    assert render_prepared_mock.await_args is not None
    prepared = render_prepared_mock.await_args.args[0]
    assert "hello world" in prepared.html
    assert prepared.stylesheets[0].css == "body { color: red; }"
    assert prepared.stylesheets[0].base_url == css_path.resolve().as_uri()
    render = render_prepared_mock.await_args.kwargs["render"]
    assert render.page.viewport.width == 420
    assert isinstance(render.screenshot, JpegScreenshotOptions)
    assert render.screenshot.quality == 66
    assert render_prepared_mock.await_args.kwargs["session"] is not None


@pytest.mark.anyio
async def test_render_markdown_reads_md_path_and_custom_css(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_markdown,
    )

    md_path = tmp_path / "sample.md"
    md_path.write_text("# Title\n\nParagraph", encoding="utf-8")
    css_path = tmp_path / "markdown.css"
    css_path.write_text(".markdown-body { color: green; }", encoding="utf-8")

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"markdown-image"),
    )

    result = await render_markdown(
        md_path=str(md_path),
        css_path=str(css_path),
        width=360,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"markdown-image"
    assert render_prepared_mock.await_args is not None
    prepared = render_prepared_mock.await_args.args[0]
    assert "<h1>Title</h1>" in prepared.html
    assert "<p>Paragraph</p>" in prepared.html
    assert prepared.stylesheets[0].css == ".markdown-body { color: green; }"
    assert prepared.stylesheets[0].base_url == css_path.resolve().as_uri()
    assert prepared.base_url == md_path.resolve().as_uri()
    render = render_prepared_mock.await_args.kwargs["render"]
    assert render.page.viewport.width == 360
    assert render_prepared_mock.await_args.kwargs["strict_assets"] is False


@pytest.mark.anyio
async def test_render_markdown_forwards_strict_resource_mode(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_markdown,
    )

    render_prepared = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"markdown-image"),
    )

    assert (
        await render_markdown(
            "![relative](relative.png)",
            resource_strict=True,
        )
        == b"markdown-image"
    )
    assert render_prepared.await_args is not None
    assert render_prepared.await_args.kwargs["strict_assets"] is True


@pytest.mark.anyio
async def test_render_markdown_requires_md_or_md_path() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_markdown,
    )

    with pytest.raises(ValueError, match="md or md_path must be provided"):
        await render_markdown()


@pytest.mark.anyio
async def test_render_template_html_requires_template_name() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template_html,
    )

    with pytest.raises(ValueError, match="template_name is required"):
        await render_template_html(str(Path.cwd()))


@pytest.mark.anyio
async def test_render_template_html_supports_custom_filters(tmp_path: Path) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template_html,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text("{{ name|caps }}", encoding="utf-8")

    result = await render_template_html(
        str(template_path),
        "card.html",
        filters={"caps": str.upper},
        name="codex",
    )

    assert result == "CODEX"


@pytest.mark.anyio
async def test_render_template_passes_rendered_html_to_prepared_renderer(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text(
        "<h1>{{ name|caps }}</h1>",
        encoding="utf-8",
    )

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"name": "codex"},
        filters={"caps": str.upper},
        pages={
            "document_url": "https://example.com/templates",
            "viewport": {"width": 300, "height": 200},
        },
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    assert render_prepared_mock.await_args is not None
    prepared = render_prepared_mock.await_args.args[0]
    render = render_prepared_mock.await_args.kwargs["render"]
    assert "<h1>CODEX</h1>" in prepared.html
    assert prepared.base_url == f"{template_path.as_uri().rstrip('/')}/"
    assert render.page.base_url == "https://example.com/templates"
    assert render.page.document_url == "https://example.com/templates"
    assert render.page.viewport.width == 300
    assert render.page.viewport.height == 200


@pytest.mark.anyio
async def test_render_template_resolves_resources_when_enabled(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}"><p>{{ name }}</p>',
        encoding="utf-8",
    )

    resolved_vars = {
        "avatar": "https://example.com/avatar.png",
        "name": "codex",
    }
    resolve_vars_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_template_vars",
        new=mocker.AsyncMock(return_value=resolved_vars),
    )
    resolve_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_html_resources",
        new=mocker.AsyncMock(
            return_value='<img src="https://example.com/avatar.png"><p>codex</p>'
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="off",
            remote_local_resource_policy="passthrough",
            local_local_resource_policy="file",
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=False,
    )
    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"avatar": template_path / "avatar.png", "name": "codex"},
        resolve_resources=True,
        resource_resolver="auto",
        resource_strict=True,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    resolve_vars_mock.assert_awaited_once()
    resolve_call = resolve_vars_mock.await_args
    assert resolve_call is not None
    assert resolve_call.args[0]["name"] == "codex"
    assert resolve_call.kwargs["template_base"] == str(template_path)
    assert resolve_call.kwargs["resolver"] == "file"
    assert resolve_call.kwargs["strict"] is True
    resolve_html_mock.assert_awaited_once()
    html_call = resolve_html_mock.await_args
    assert html_call is not None
    assert html_call.kwargs["template_base"] == str(template_path)
    assert html_call.kwargs["resolver"] == "file"
    assert html_call.kwargs["strict"] is True
    assert render_prepared_mock.await_args is not None
    prepared = render_prepared_mock.await_args.args[0]
    assert '<img src="https://example.com/avatar.png">' in prepared.html


@pytest.mark.parametrize(
    ("session", "static_remote"),
    [
        pytest.param(_SessionStub(mode="remote_ws"), False, id="endpoint-session"),
        pytest.param(None, True, id="static-connect-ws"),
    ],
)
@pytest.mark.anyio
async def test_render_template_auto_resolver_uses_actual_remote_session_policy(
    mocker: MockerFixture,
    tmp_path: Path,
    session: _SessionStub | None,
    *,
    static_remote: bool,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        operations,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    asset = template_path / "avatar.png"
    asset.write_bytes(b"png")
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}"><span>{{ payload }}</span>',
        encoding="utf-8",
    )

    mocker.patch.object(
        operations,
        "get_playwright_config",
        return_value=SimpleNamespace(
            resource_resolve_mode="auto",
            remote_local_resource_policy="memory",
            local_local_resource_policy="file",
        ),
    )
    mocker.patch.object(
        operations,
        "is_remote_playwright_mode",
        return_value=static_remote,
    )
    resolve_vars_spy = mocker.spy(operations, "resolve_template_vars")
    resolve_html_spy = mocker.spy(operations, "resolve_html_resources")
    register_root = mocker.patch.object(operations, "register_filehost_resource_root")
    create_lease = mocker.patch.object(operations, "create_filehost_lease")
    release_lease = mocker.patch.object(
        operations,
        "release_filehost_lease",
        new=mocker.AsyncMock(),
    )
    render_prepared = mocker.patch.object(
        operations,
        "render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await operations.render_template(
        str(template_path),
        "card.html",
        templates={"avatar": asset, "payload": b"strict-bytes"},
        resource_resolver="auto",
        resource_strict=True,
        session=session,
    )

    assert result == b"template-image"
    assert resolve_vars_spy.await_args is not None
    assert resolve_vars_spy.await_args.kwargs["resolver"] == "memory"
    assert resolve_html_spy.await_args is not None
    assert resolve_html_spy.await_args.kwargs["resolver"] == "memory"
    render_prepared.assert_awaited_once()
    assert render_prepared.await_args is not None
    prepared = render_prepared.await_args.args[0]
    assert asset.as_uri() in prepared.html
    assert "memory://htmlrender/template-assets/" in prepared.html
    assert len(prepared.assets) == 1
    assert prepared.assets[0].data == b"strict-bytes"
    assert prepared.assets[0].media_type == "application/octet-stream"
    register_root.assert_not_called()
    create_lease.assert_not_called()
    release_lease.assert_not_called()


@pytest.mark.parametrize(
    ("session", "static_remote"),
    [
        pytest.param(_SessionStub(mode="remote_ws"), False, id="endpoint-session"),
        pytest.param(None, True, id="static-connect-ws"),
    ],
)
@pytest.mark.anyio
async def test_render_template_filehost_resolver_matches_remote_session_sources(
    mocker: MockerFixture,
    tmp_path: Path,
    session: _SessionStub | None,
    *,
    static_remote: bool,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        operations,
    )
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve as resolve_module,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    asset = template_path / "avatar.png"
    asset.write_bytes(b"png")
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}"><img src="{{ payload }}">',
        encoding="utf-8",
    )

    mocker.patch.object(
        operations,
        "get_playwright_config",
        return_value=SimpleNamespace(
            resource_resolve_mode="auto",
            remote_local_resource_policy="filehost",
            local_local_resource_policy="file",
        ),
    )
    mocker.patch.object(
        operations,
        "is_remote_playwright_mode",
        return_value=static_remote,
    )

    async def resolve_filehost(value: object, *, lease_id: str | None = None) -> str:
        suffix = "path" if isinstance(value, Path) else "bytes"
        return f"https://assets.example/{suffix}?lease={lease_id}"

    filehost_url = mocker.patch.object(
        resolve_module,
        "filehost_url",
        side_effect=resolve_filehost,
    )
    resolve_vars_spy = mocker.spy(operations, "resolve_template_vars")
    resolve_html_spy = mocker.spy(operations, "resolve_html_resources")
    register_root = mocker.patch.object(operations, "register_filehost_resource_root")
    create_lease = mocker.patch.object(
        operations,
        "create_filehost_lease",
        return_value="lease:test",
    )
    release_lease = mocker.patch.object(
        operations,
        "release_filehost_lease",
        new=mocker.AsyncMock(),
    )
    render_prepared = mocker.patch.object(
        operations,
        "render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await operations.render_template(
        str(template_path),
        "card.html",
        templates={"avatar": asset, "payload": b"strict-bytes"},
        resource_resolver="auto",
        resource_strict=True,
        session=session,
    )

    assert result == b"template-image"
    assert resolve_vars_spy.await_args is not None
    assert resolve_vars_spy.await_args.kwargs["resolver"] == "filehost"
    assert resolve_html_spy.await_args is not None
    assert resolve_html_spy.await_args.kwargs["resolver"] == "filehost"
    assert filehost_url.await_count == 2
    assert all(
        call.kwargs["lease_id"] == "lease:test" for call in filehost_url.await_args_list
    )
    register_root.assert_called_once_with(str(template_path))
    create_lease.assert_called_once_with()
    release_lease.assert_awaited_once_with("lease:test")
    render_prepared.assert_awaited_once()


@pytest.mark.anyio
async def test_render_template_skips_resource_resolution_when_disabled(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text("{{ name }}", encoding="utf-8")

    resolve_vars_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_template_vars",
        new=mocker.AsyncMock(),
    )
    resolve_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.resolve_html_resources",
        new=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="auto",
            remote_local_resource_policy="passthrough",
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=False,
    )
    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"name": "codex"},
        resolve_resources=False,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    resolve_vars_mock.assert_not_called()
    resolve_html_mock.assert_not_called()
    assert render_prepared_mock.await_args is not None


@pytest.mark.anyio
async def test_render_template_forwards_explicit_file_document_url(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        PageConfig,
        PngScreenshotOptions,
        RenderConfig,
        TemplateConfig,
        TemplateRenderRequest,
        ViewportConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="off",
            remote_local_resource_policy="filehost",
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=True,
    )

    (tmp_path / "unused.html").write_text("<p>ok</p>", encoding="utf-8")
    request = TemplateRenderRequest(
        template=TemplateConfig(
            template_path=str(tmp_path),
            template_name="unused.html",
            template_vars={"name": "codex"},
            custom_filters={},
        ),
        render=RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(width=500, height=10),
                document_url="file:///tmp/templates",
            ),
            screenshot=PngScreenshotOptions(
                device_scale_factor=2.0,
                timeout=30_000,
                full_page=True,
                wait_before_screenshot=0,
            ),
        ),
    )

    result = await render_template(request, session=object())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]

    assert result == b"template-image"
    assert render_prepared_mock.await_args is not None
    forwarded_render = render_prepared_mock.await_args.kwargs["render"]
    assert forwarded_render.page.document_url == "file:///tmp/templates"


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


@pytest.mark.anyio
async def test_render_template_raises_early_on_remote_pna_risk(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}">',
        encoding="utf-8",
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="auto",
            remote_local_resource_policy="filehost",
        ),
    )

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    with pytest.raises(RuntimeError, match="PNA precheck failed"):
        await render_template(
            str(template_path),
            "card.html",
            templates={"avatar": "http://render:9012/filehost/abc"},
            pages={"document_url": "about:blank"},
            resolve_resources=False,
            resource_strict=True,
            session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        )

    render_prepared_mock.assert_not_called()


@pytest.mark.anyio
async def test_render_template_allows_remote_private_resource_with_same_origin(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}">',
        encoding="utf-8",
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="auto",
            remote_local_resource_policy="filehost",
        ),
    )

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"avatar": "http://render:9012/filehost/abc"},
        pages={"document_url": "http://render:9012/"},
        resolve_resources=False,
        resource_strict=True,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    render_prepared_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_render_template_warns_but_continues_on_remote_pna_risk_when_not_strict(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template,
    )

    template_path = tmp_path / "templates"
    template_path.mkdir()
    (template_path / "card.html").write_text(
        '<img src="{{ avatar }}">',
        encoding="utf-8",
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=mocker.Mock(
            resource_resolve_mode="auto",
            remote_local_resource_policy="filehost",
        ),
    )
    warning_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.logger.warning"
    )

    render_prepared_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"avatar": "http://render:9012/filehost/abc?token=secret"},
        pages={"document_url": "about:blank"},
        resolve_resources=False,
        resource_strict=False,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    render_prepared_mock.assert_awaited_once()
    assert any(
        "PNA precheck failed" in str(call.args[0])
        for call in warning_mock.call_args_list
    )
    assert not any(
        "token=secret" in str(call.args[0]) for call in warning_mock.call_args_list
    )


def test_operations_redact_url_masks_credentials_and_query() -> None:
    from nonebot_plugin_htmlrender.backend.playwright._page import (  # noqa: PLC0415
        _redact_url,
    )

    redacted = _redact_url("https://user:pass@example.com:8443/path?a=1#x")
    assert redacted == "https://example.com:8443/path"


@pytest.mark.anyio
async def test_compat_template_to_pic_rejects_resource_resolution_options() -> None:
    from nonebot_plugin_htmlrender._compat import template_to_pic  # noqa: PLC0415

    with pytest.raises(TypeError, match="resolve_resources"):
        await template_to_pic(
            str(Path.cwd()),
            "card.html",
            {},
            resolve_resources=True,  # type: ignore[call-arg]  # ty: ignore[unknown-argument]
        )


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


@pytest.mark.anyio
async def test_render_template_html_accepts_template_config(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.models import (  # noqa: PLC0415
        TemplateConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_template_html,
    )

    cfg = TemplateConfig(
        template_path=str(Path.cwd()),
        template_name="a.html",
        template_vars={"name": "codex"},
        custom_filters={},
    )
    render_jinja = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_jinja_template_html",
        new=mocker.AsyncMock(return_value="ok"),
    )
    assert await render_template_html(cfg) == "ok"
    render_jinja.assert_awaited_once_with(
        cfg.template_path,
        cfg.template_name,
        cfg.template_vars,
        filters=None,
    )


@pytest.mark.anyio
async def test_render_html_string_request_and_event_callbacks(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_html,
    )

    page = mocker.AsyncMock()
    page.on = mocker.MagicMock()
    page.screenshot = mocker.AsyncMock(return_value=b"png")
    cm = mocker.MagicMock()
    cm.__aenter__ = mocker.AsyncMock(return_value=page)
    cm.__aexit__ = mocker.AsyncMock(return_value=None)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=cm,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.get_playwright_config",
        return_value=SimpleNamespace(
            remote_local_resource_policy=SimpleNamespace(value="filehost")
        ),
    )
    install_route = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.install_filehost_request_route",
        new=mocker.AsyncMock(),
    )
    warning = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.logger.warning"
    )

    result = await render_html(
        "<main>x</main>", template_path="https://example.com/base"
    )
    assert result == b"png"
    install_route.assert_awaited_once()
    page.screenshot.assert_awaited_once()
    await_args = page.screenshot.await_args
    assert await_args is not None
    assert await_args.kwargs["type"] == "png"

    handlers = {call.args[0]: call.args[1] for call in page.on.call_args_list}
    request = SimpleNamespace(
        url="https://example.com/a.png",
        method="GET",
        resource_type="image",
        failure="bad",
    )
    handlers["requestfailed"](request)
    response = SimpleNamespace(
        url="https://example.com/a.png",
        status=500,
        request=SimpleNamespace(resource_type="image"),
    )
    handlers["response"](response)
    assert warning.call_count >= 2


@pytest.mark.anyio
async def test_operation_compat_wrappers_delegate(
    mocker: MockerFixture,
) -> None:
    """Deprecated wrappers in data_source delegate to operations."""
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        data_source as pw_data_source,
    )

    mocker.patch.object(
        pw_data_source._operations,
        "render_text",
        new=mocker.AsyncMock(return_value=b"a"),
    )
    mocker.patch.object(
        pw_data_source._operations,
        "render_markdown",
        new=mocker.AsyncMock(return_value=b"b"),
    )
    mocker.patch.object(
        pw_data_source._operations,
        "render_template_html",
        new=mocker.AsyncMock(return_value="c"),
    )
    mocker.patch.object(
        pw_data_source._operations,
        "render_html",
        new=mocker.AsyncMock(return_value=b"d"),
    )
    mocker.patch.object(
        pw_data_source._operations,
        "render_template",
        new=mocker.AsyncMock(return_value=b"e"),
    )
    mocker.patch.object(
        pw_data_source._operations,
        "capture_html_element",
        new=mocker.AsyncMock(return_value=b"f"),
    )

    assert await pw_data_source.text_to_pic("x") == b"a"
    assert await pw_data_source.md_to_pic("x") == b"b"
    assert await pw_data_source.template_to_html("t", "n") == "c"
    assert await pw_data_source.html_to_pic("<p/>") == b"d"
    assert await pw_data_source.template_to_pic("t", "n", {}) == b"e"
    assert await pw_data_source.capture_element("u", "#e") == b"f"
