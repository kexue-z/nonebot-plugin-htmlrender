from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture


def test_resolve_mode_variants(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteCDPConfig,
        RemoteWSConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )

    backend = PlaywrightBackend()

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(),
    )
    assert backend._resolve_mode() is PlaywrightMode.LOCAL

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(
            connect_ws=RemoteWSConfig(endpoint="ws://example.com/ws"),
        ),
    )
    assert backend._resolve_mode() is PlaywrightMode.REMOTE_WS

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(
            connect_cdp=RemoteCDPConfig(endpoint="http://example.com/json/version"),
        ),
    )
    assert backend._resolve_mode() is PlaywrightMode.REMOTE_CDP


def test_resolve_mode_rejects_multiple_remote_endpoints(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(
            connect_ws=SimpleNamespace(endpoint="ws://example.com/ws"),
            connect_cdp=SimpleNamespace(endpoint="http://example.com/json/version"),
        ),
    )

    with pytest.raises(RuntimeError, match="cannot both be set"):
        backend._resolve_mode()


def test_build_proxy() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    assert PlaywrightBackend._build_proxy("http://proxy:7890") == {
        "server": "http://proxy:7890",
    }
    assert PlaywrightBackend._build_proxy(
        "http://proxy:7890",
        "localhost,127.0.0.1",
    ) == {
        "server": "http://proxy:7890",
        "bypass": "localhost,127.0.0.1",
    }


def test_backend_redact_url_masks_credentials_and_query() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    redacted = PlaywrightBackend._redact_url(
        "wss://user:pass@example.com/ws?token=abc#frag"
    )
    assert redacted == "wss://example.com/ws"


@pytest.mark.anyio
async def test_startup_steps_include_filehost_prewarm(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()

    prepare_env_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.prepare_playwright_env_vars"
    )
    reconcile_cache_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.reconcile_legacy_playwright_cache"
    )
    record_state_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.record_playwright_runtime_state"
    )
    prewarm_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.ensure_filehost_runtime_ready",
        new=mocker.AsyncMock(return_value=True),
    )

    async def run_sync_side_effect(func, *args, **kwargs):
        return func(*args, **kwargs)

    run_sync_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.run_sync",
        new=mocker.AsyncMock(side_effect=run_sync_side_effect),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=type("Cfg", (), {"cleanup_legacy_cache": True})(),
    )

    steps = backend.startup_steps()
    assert len(steps) == 4

    for step in steps:
        await step()

    assert run_sync_mock.await_count == 3
    prepare_env_mock.assert_called_once_with()
    reconcile_cache_mock.assert_called_once_with(cleanup=True)
    record_state_mock.assert_called_once_with()
    prewarm_mock.assert_awaited_once_with(reason="playwright_startup")


@pytest.mark.anyio
async def test_create_browser_remote_cdp_connects_with_clean_kwargs(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteCDPConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )

    backend = PlaywrightBackend()
    connect_mock = mocker.AsyncMock(return_value="cdp-browser")
    pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect_mock))

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(
            connect_cdp=RemoteCDPConfig(endpoint="http://localhost:9222"),
        ),
    )

    result = await backend._create_browser(
        pw,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        PlaywrightMode.REMOTE_CDP,
        endpoint_url="ignored",
        slow_mo=50,
    )

    assert result == "cdp-browser"
    connect_mock.assert_awaited_once_with("http://localhost:9222", slow_mo=50)


@pytest.mark.anyio
async def test_create_browser_remote_cdp_requires_chromium(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    backend = PlaywrightBackend()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(
            engine=BrowserEngine.FIREFOX,
            connect_cdp=SimpleNamespace(endpoint="http://localhost:9222"),
        ),
    )

    with pytest.raises(RuntimeError, match="CDP connection requires"):
        await backend._create_browser(
            SimpleNamespace(),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
            PlaywrightMode.REMOTE_CDP,
        )


@pytest.mark.anyio
async def test_create_browser_remote_ws_connects_after_version_gate(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteWSConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    backend = PlaywrightBackend()
    connect_mock = mocker.AsyncMock(return_value="ws-browser")
    pw = SimpleNamespace(firefox=SimpleNamespace(connect=connect_mock))

    check_ws_gate_mock = mocker.patch.object(backend, "_check_ws_version_gate")
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(
            engine=BrowserEngine.FIREFOX,
            connect_ws=RemoteWSConfig(endpoint="ws://localhost:3000/ws"),
        ),
    )

    result = await backend._create_browser(
        pw,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        PlaywrightMode.REMOTE_WS,
        ws_endpoint="ignored",
        timeout=4_000,
    )

    assert result == "ws-browser"
    check_ws_gate_mock.assert_called_once_with()
    connect_mock.assert_awaited_once_with("ws://localhost:3000/ws", timeout=4_000)


@pytest.mark.anyio
async def test_create_browser_local_launches_with_channel_proxy_args_and_executable(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )
    from nonebot_plugin_htmlrender.consts import ChromiumChannel  # noqa: PLC0415

    backend = PlaywrightBackend()
    launch_mock = mocker.AsyncMock(return_value="local-browser")
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=launch_mock))

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(
            channel=ChromiumChannel.CHROME,
            executable_path=Path("/custom/chrome"),
            proxy_server="http://proxy:8080",
            proxy_bypass="localhost",
            launch_args="--headless=new --lang=en-US",
        ),
    )

    result = await backend._create_browser(
        pw,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        PlaywrightMode.LOCAL,
        headless=True,
    )

    assert result == "local-browser"
    launch_mock.assert_awaited_once_with(
        headless=True,
        channel="chrome",
        proxy={"server": "http://proxy:8080", "bypass": "localhost"},
        args=["--headless=new", "--lang=en-US"],
        executable_path="/custom/chrome",
    )


@pytest.mark.anyio
async def test_create_browser_local_uses_env_check_when_no_custom_executable(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )

    backend = PlaywrightBackend()
    check_env_mock = mocker.patch.object(
        backend,
        "_check_env_with_install_retry",
        new=mocker.AsyncMock(return_value="checked-browser"),
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(),
    )

    result = await backend._create_browser(
        SimpleNamespace(chromium=SimpleNamespace()),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        PlaywrightMode.LOCAL,
        headless=False,
    )

    assert result == "checked-browser"
    check_env_mock.assert_awaited_once()
    assert check_env_mock.await_args is not None
    assert check_env_mock.await_args.args[0].chromium is not None
    assert check_env_mock.await_args.kwargs == {"headless": False}


@pytest.mark.anyio
async def test_check_env_with_install_retry_respects_skip_flag(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()
    mocker.patch.object(
        backend,
        "_check_playwright_env",
        new=mocker.AsyncMock(side_effect=RuntimeError("env missing")),
    )
    install_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.install_browser",
        new=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(skip_browser_install=True),
    )
    wrapped = unwrap(PlaywrightBackend._check_env_with_install_retry)

    with pytest.raises(RuntimeError, match="env missing"):
        await wrapped(
            backend,
            SimpleNamespace(),
            headless=True,
        )

    install_mock.assert_not_awaited()


@pytest.mark.anyio
async def test_check_env_with_install_retry_attempts_install_on_failure(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()
    mocker.patch.object(
        backend,
        "_check_playwright_env",
        new=mocker.AsyncMock(side_effect=RuntimeError("env missing")),
    )
    install_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.install_browser",
        new=mocker.AsyncMock(return_value=True),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=PlaywrightConfig(skip_browser_install=False),
    )
    wrapped = unwrap(PlaywrightBackend._check_env_with_install_retry)

    with pytest.raises(RuntimeError, match="env missing"):
        await wrapped(
            backend,
            SimpleNamespace(),
        )

    install_mock.assert_awaited_once_with()


def test_semver_helpers_cover_safe_warning_and_block_paths() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        WsVersionRiskLevel,
    )

    assert PlaywrightBackend._parse_semver("1.55.3") == (1, 55, 3)
    assert PlaywrightBackend._parse_semver("version=unknown") is None
    assert (
        PlaywrightBackend._evaluate_ws_version_risk((1, 55, 3), (1, 55, 9))
        is WsVersionRiskLevel.SAFE
    )
    assert (
        PlaywrightBackend._evaluate_ws_version_risk((1, 55, 3), (1, 56, 0))
        is WsVersionRiskLevel.WARNING
    )
    assert (
        PlaywrightBackend._evaluate_ws_version_risk((1, 55, 3), (2, 0, 0))
        is WsVersionRiskLevel.BLOCK
    )
    assert PlaywrightBackend._extract_version_from_endpoint(
        "ws://host/playwright-1.54.2/devtools"
    ) == (1, 54, 2)
    assert PlaywrightBackend._extract_version_from_endpoint(
        "ws://host/browser?playwright_version=1.55.1"
    ) == (1, 55, 1)


def test_detect_remote_ws_version_falls_back_to_http_probe(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    extract_mock = mocker.patch.object(
        PlaywrightBackend,
        "_extract_version_from_endpoint",
        return_value=None,
    )
    probe_mock = mocker.patch.object(
        PlaywrightBackend,
        "_probe_ws_http_version",
        return_value=(1, 55, 3),
    )

    assert PlaywrightBackend._detect_remote_ws_version("ws://host/browser") == (
        1,
        55,
        3,
    )
    extract_mock.assert_called_once_with("ws://host/browser")
    probe_mock.assert_called_once_with("ws://host/browser")


def test_ws_version_gate_allows_unknown_remote_version(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(
            connect_ws=SimpleNamespace(endpoint="ws://host/playwright")
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.pkg_version",
        return_value="1.58.0",
    )
    detect_mock = mocker.patch.object(
        backend,
        "_detect_remote_ws_version",
        return_value=None,
    )
    warning_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.logger.warning"
    )

    backend._check_ws_version_gate()

    detect_mock.assert_called_once_with("ws://host/playwright")
    warning_mock.assert_called_once()


def test_endpoint_and_channel_helpers(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        _channel_command_candidates,
        _has_available_channel_browser,
        _has_valid_remote_endpoint,
    )

    assert _has_valid_remote_endpoint("wss://host/path", schemes={"ws", "wss"}) is True
    assert _has_valid_remote_endpoint("ftp://host/path", schemes={"ws", "wss"}) is False
    assert _channel_command_candidates("chrome-beta") == (
        "google-chrome-beta",
        "chrome-beta",
    )
    assert _channel_command_candidates("custom-browser") == ("custom-browser",)

    which_mock = mocker.patch(
        "shutil.which", side_effect=[None, "/usr/bin/chrome-beta"]
    )
    assert _has_available_channel_browser("chrome-beta") is True
    assert which_mock.call_count == 2


def test_playwright_backend_availability_branches(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.factory import (  # noqa: PLC0415
        BackendAvailability,
    )
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteCDPConfig,
        RemoteWSConfig,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        is_playwright_backend_available,
    )
    from nonebot_plugin_htmlrender.consts import ChromiumChannel  # noqa: PLC0415

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.find_spec",
        return_value=object(),
    )

    invalid_cfg = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        side_effect=RuntimeError("bad config"),
    )
    availability = is_playwright_backend_available()
    assert availability == BackendAvailability(
        available=False,
        reason="Invalid Playwright config: bad config",
    )
    invalid_cfg.side_effect = None
    invalid_cfg.return_value = PlaywrightConfig()

    availability = is_playwright_backend_available()
    assert availability == BackendAvailability(
        available=True,
        reason=None,
    )

    invalid_cfg.return_value = PlaywrightConfig(
        connect_ws=RemoteWSConfig(endpoint="not-a-ws-endpoint"),
    )
    availability = is_playwright_backend_available()
    assert availability.available is False
    assert availability.reason == "Configured WebSocket endpoint is invalid."

    invalid_cfg.return_value = PlaywrightConfig(
        connect_cdp=RemoteCDPConfig(endpoint="http://localhost:9222"),
    )
    assert is_playwright_backend_available() == BackendAvailability(available=True)

    invalid_cfg.return_value = PlaywrightConfig(executable_path=tmp_path / "chrome")
    availability = is_playwright_backend_available()
    assert availability.available is False
    assert availability.reason is not None
    assert "Configured executable does not exist" in availability.reason

    executable_path = tmp_path / "chrome"
    executable_path.write_text("", encoding="utf-8")
    invalid_cfg.return_value = PlaywrightConfig(executable_path=executable_path)
    assert is_playwright_backend_available() == BackendAvailability(available=True)

    invalid_cfg.return_value = PlaywrightConfig(channel=ChromiumChannel.CHROME)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render._has_available_channel_browser",
        return_value=False,
    )
    availability = is_playwright_backend_available()
    assert availability.available is False
    assert availability.reason == (
        "Configured browser channel `chrome` is not available on PATH."
    )

    invalid_cfg.return_value = PlaywrightConfig(skip_browser_install=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.has_installed_browser",
        return_value=False,
    )
    availability = is_playwright_backend_available()
    assert availability.available is False
    assert availability.reason is not None
    assert "skip_browser_install=true" in availability.reason


def test_playwright_backend_unavailable_without_python_package(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.factory import (  # noqa: PLC0415
        BackendAvailability,
    )
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        is_playwright_backend_available,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.find_spec",
        return_value=None,
    )

    assert is_playwright_backend_available() == BackendAvailability(
        available=False,
        reason="Python package `playwright` is not installed.",
    )


@pytest.mark.anyio
async def test_create_runtime_and_session_close_paths(
    mocker: MockerFixture,
) -> None:
    from playwright.async_api import Browser, Playwright  # noqa: PLC0415

    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )

    backend = PlaywrightBackend()
    pw = mocker.MagicMock(spec=Playwright)
    pw.stop = mocker.AsyncMock()
    async_playwright_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.async_playwright"
    )
    async_playwright_mock.return_value.start = mocker.AsyncMock(return_value=pw)
    clear_env = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.clear_playwright_env_vars"
    )

    runtime = await backend.create_runtime()
    await runtime.aclose()
    pw.stop.assert_awaited_once_with()
    clear_env.assert_called_once_with()

    browser = mocker.MagicMock(spec=Browser)
    browser.is_connected = mocker.Mock(return_value=True)
    browser.close = mocker.AsyncMock()
    mocker.patch.object(backend, "_resolve_mode", return_value=PlaywrightMode.LOCAL)
    mocker.patch.object(
        backend, "_create_browser", new=mocker.AsyncMock(return_value=browser)
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(close_on_exit=True),
    )
    session = await backend.create_session(runtime)
    await session.aclose()
    browser.close.assert_awaited_once_with()


def test_backend_is_alive_and_redact_parse_error(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.urlsplit",
        side_effect=ValueError,
    )
    assert backend._redact_url("invalid url") == "invalid url"


@pytest.mark.anyio
async def test_get_render_context_and_backend_operation_wrappers(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()

    render_html = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.render_html",
        new=mocker.AsyncMock(return_value=b"h"),
    )
    render_text = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.render_text",
        new=mocker.AsyncMock(return_value=b"t"),
    )
    render_markdown = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.render_markdown",
        new=mocker.AsyncMock(return_value=b"m"),
    )
    render_template = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.render_template",
        new=mocker.AsyncMock(return_value=b"tp"),
    )
    render_template_html = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.render_template_html",
        new=mocker.AsyncMock(return_value="th"),
    )
    capture = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.playwright_operations.capture_html_element",
        new=mocker.AsyncMock(return_value=b"c"),
    )

    assert await backend.render_html(object(), "<p/>") == b"h"  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    assert await backend.render_text(object(), "x") == b"t"  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    assert await backend.render_markdown(object(), markdown_text="x") == b"m"  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    assert await backend.render_template(object(), "tpl") == b"tp"  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    assert await backend.render_template_html("tpl") == "th"
    assert await backend.capture_html_element(object(), "u", "#e") == b"c"  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    render_html.assert_awaited_once()
    render_text.assert_awaited_once()
    render_markdown.assert_awaited_once()
    render_template.assert_awaited_once()
    render_template_html.assert_awaited_once()
    capture.assert_awaited_once()


@pytest.mark.anyio
async def test_create_browser_empty_endpoints_and_install_exception(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        PlaywrightMode,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    backend = PlaywrightBackend()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(
            engine=BrowserEngine.CHROMIUM,
            connect_cdp=SimpleNamespace(endpoint=""),
            connect_ws=SimpleNamespace(endpoint=""),
        ),
    )
    with pytest.raises(RuntimeError, match="CDP endpoint is empty"):
        await backend._create_browser(
            SimpleNamespace(chromium=SimpleNamespace()),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
            PlaywrightMode.REMOTE_CDP,
        )
    with pytest.raises(RuntimeError, match="WS endpoint is empty"):
        await backend._create_browser(
            SimpleNamespace(chromium=SimpleNamespace()),  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
            PlaywrightMode.REMOTE_WS,
        )

    mocker.patch.object(
        backend,
        "_check_playwright_env",
        new=mocker.AsyncMock(side_effect=RuntimeError("env missing")),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(skip_browser_install=False),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.install_browser",
        new=mocker.AsyncMock(side_effect=ValueError("install failed")),
    )
    wrapped = unwrap(PlaywrightBackend._check_env_with_install_retry)
    with pytest.raises(RuntimeError, match="install_browser failed"):
        await wrapped(backend, SimpleNamespace())


@pytest.mark.anyio
async def test_check_playwright_env_wraps_runtime_error(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    backend = PlaywrightBackend()
    browser_type = SimpleNamespace(
        launch=mocker.AsyncMock(side_effect=RuntimeError("broken"))
    )
    mocker.patch.object(backend, "_get_browser_type", return_value=browser_type)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(engine=SimpleNamespace(value="chromium")),
    )

    with pytest.raises(
        RuntimeError, match="Playwright environment is not set up correctly"
    ):
        await backend._check_playwright_env(SimpleNamespace())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_version_gate_probe_and_risk_variants(mocker: MockerFixture) -> None:
    from importlib.metadata import PackageNotFoundError  # noqa: PLC0415

    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
        WsVersionRiskLevel,
    )

    assert (
        PlaywrightBackend._evaluate_ws_version_risk((1, 55, 3), (1, 57, 0))
        is WsVersionRiskLevel.BLOCK
    )
    assert (
        PlaywrightBackend._evaluate_ws_version_risk((1, 55, 3), (1, 55, 20))
        is WsVersionRiskLevel.WARNING
    )
    assert PlaywrightBackend._probe_ws_http_version("http://example.com/ws") is None

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return b'{"Browser":"Playwright/1.55.2"}'

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.urlopen",
        return_value=_Resp(),
    )
    assert PlaywrightBackend._probe_ws_http_version("ws://localhost/ws") == (1, 55, 2)

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.urlopen",
        side_effect=RuntimeError("down"),
    )
    assert PlaywrightBackend._probe_ws_http_version("ws://localhost/ws") is None
    assert PlaywrightBackend._detect_remote_ws_version(
        "ws://host?playwright_version=1.2.3"
    ) == (
        1,
        2,
        3,
    )

    backend = PlaywrightBackend()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(connect_ws=SimpleNamespace(endpoint="")),
    )
    with pytest.raises(RuntimeError, match="WS endpoint is empty"):
        backend._check_ws_version_gate()

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=SimpleNamespace(
            connect_ws=SimpleNamespace(endpoint="ws://host/ws")
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.pkg_version",
        side_effect=PackageNotFoundError("playwright"),
    )
    with pytest.raises(
        RuntimeError, match="Local playwright package version is unavailable"
    ):
        backend._check_ws_version_gate()

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.pkg_version",
        return_value="unknown",
    )
    with pytest.raises(RuntimeError, match="Invalid local playwright version format"):
        backend._check_ws_version_gate()

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.pkg_version",
        return_value="1.55.0",
    )
    mocker.patch.object(backend, "_detect_remote_ws_version", return_value=(1, 56, 0))
    backend._check_ws_version_gate()
    mocker.patch.object(backend, "_detect_remote_ws_version", return_value=(2, 0, 0))
    with pytest.raises(
        RuntimeError, match="WS version mismatch is out of allowed range"
    ):
        backend._check_ws_version_gate()


def test_availability_additional_branches(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
        is_playwright_backend_available,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.find_spec",
        return_value=object(),
    )
    cfg = SimpleNamespace(
        connect_cdp=SimpleNamespace(endpoint="http://localhost:9222"),
        connect_ws=SimpleNamespace(endpoint=""),
        executable_path=None,
        channel=None,
        skip_browser_install=True,
        engine=BrowserEngine.CHROMIUM,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.get_playwright_config",
        return_value=cfg,
    )
    cfg.connect_cdp.endpoint = "bad-endpoint"
    status = is_playwright_backend_available()
    assert status.available is False
    assert "CDP endpoint is invalid" in (status.reason or "")

    cfg.connect_cdp.endpoint = ""
    cfg.connect_ws.endpoint = "ws://host/ws"
    assert is_playwright_backend_available().available is True

    cfg.connect_ws.endpoint = ""
    cfg.channel = SimpleNamespace(value="chrome")
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render._has_available_channel_browser",
        return_value=True,
    )
    assert is_playwright_backend_available().available is True

    cfg.channel = None
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render.has_installed_browser",
        return_value=True,
    )
    assert is_playwright_backend_available().available is True
