from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture


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
    assert request.render.page.base_url == "https://example.com/base"
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

    assert request.render.page.base_url == f"file://{Path.cwd()}"
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
                base_url="https://example.com",
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
    page.set_content.assert_awaited_once_with(
        "<section>ok</section>", wait_until="load"
    )
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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
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
    assert render_html_mock.await_args is not None
    request = render_html_mock.await_args.args[0]
    assert "hello world" in request.content.html
    assert "body { color: red; }" in request.content.html
    assert request.render.page.base_url == css_path.resolve().as_uri()
    assert request.render.page.viewport.width == 420
    assert isinstance(request.render.screenshot, JpegScreenshotOptions)
    assert request.render.screenshot.quality == 66
    assert render_html_mock.await_args.kwargs["session"] is not None


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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"markdown-image"),
    )

    result = await render_markdown(
        md_path=str(md_path),
        css_path=str(css_path),
        width=360,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"markdown-image"
    assert render_html_mock.await_args is not None
    request = render_html_mock.await_args.args[0]
    assert "<h1>Title</h1>" in request.content.html
    assert "<p>Paragraph</p>" in request.content.html
    assert ".markdown-body { color: green; }" in request.content.html
    assert request.render.page.base_url == css_path.resolve().as_uri()
    assert request.render.page.viewport.width == 360


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
async def test_render_template_passes_rendered_html_to_render_html(
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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"name": "codex"},
        filters={"caps": str.upper},
        pages={
            "base_url": "https://example.com/templates",
            "viewport": {"width": 300, "height": 200},
        },
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    assert render_html_mock.await_args is not None
    request = render_html_mock.await_args.args[0]
    assert "<h1>CODEX</h1>" in request.content.html
    assert request.render.page.base_url == "https://example.com/templates"
    assert request.render.page.viewport.width == 300
    assert request.render.page.viewport.height == 200


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
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.is_remote_playwright_mode",
        return_value=False,
    )
    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
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
    assert resolve_call.kwargs["resolver"] == "auto"
    assert resolve_call.kwargs["strict"] is True
    resolve_html_mock.assert_awaited_once()
    html_call = resolve_html_mock.await_args
    assert html_call is not None
    assert html_call.kwargs["template_base"] == str(template_path)
    assert html_call.kwargs["resolver"] == "auto"
    assert html_call.kwargs["strict"] is True
    assert render_html_mock.await_args is not None
    request = render_html_mock.await_args.args[0]
    assert '<img src="https://example.com/avatar.png">' in request.content.html


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
    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
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
    assert render_html_mock.await_args is not None


@pytest.mark.anyio
async def test_render_template_warns_remote_file_base_url(
    mocker: MockerFixture,
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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )
    warning_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.logger.warning"
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

    request = TemplateRenderRequest(
        template=TemplateConfig(
            template_path=str(Path.cwd()),
            template_name="unused.html",
            template_vars={"name": "codex"},
            custom_filters={},
        ),
        render=RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(width=500, height=10),
                base_url="file:///tmp/templates",
            ),
            screenshot=PngScreenshotOptions(
                device_scale_factor=2.0,
                timeout=30_000,
                full_page=True,
                wait_before_screenshot=0,
            ),
        ),
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.jinja2.Environment.get_template",
        return_value=mocker.Mock(
            render_async=mocker.AsyncMock(return_value="<p>ok</p>"),
        ),
    )

    result = await render_template(request, session=object())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]

    assert result == b"template-image"
    warning_mock.assert_called_once()
    assert render_html_mock.await_args is not None


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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    with pytest.raises(RuntimeError, match="PNA precheck failed"):
        await render_template(
            str(template_path),
            "card.html",
            templates={"avatar": "http://render:9012/filehost/abc"},
            pages={"base_url": "about:blank"},
            resolve_resources=False,
            resource_strict=True,
            session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        )

    render_html_mock.assert_not_called()


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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"avatar": "http://render:9012/filehost/abc"},
        pages={"base_url": "http://render:9012/"},
        resolve_resources=False,
        resource_strict=True,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    render_html_mock.assert_awaited_once()


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

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"template-image"),
    )

    result = await render_template(
        str(template_path),
        "card.html",
        templates={"avatar": "http://render:9012/filehost/abc?token=secret"},
        pages={"base_url": "about:blank"},
        resolve_resources=False,
        resource_strict=False,
        session=object(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == b"template-image"
    render_html_mock.assert_awaited_once()
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
    env = mocker.Mock()
    template = mocker.Mock(render_async=mocker.AsyncMock(return_value="ok"))
    env.get_template.return_value = template
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.jinja2.Environment",
        return_value=env,
    )
    assert await render_template_html(cfg) == "ok"


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
