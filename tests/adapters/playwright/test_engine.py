from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from exceptiongroup import BaseExceptionGroup
import pytest

from nonebot_plugin_htmlrender.adapters.playwright.availability import (
    playwright_availability,
)
from nonebot_plugin_htmlrender.adapters.playwright.config import (
    BrowserEngine,
    ChromiumChannel,
    PlaywrightConfig,
)
from nonebot_plugin_htmlrender.adapters.playwright.render import (
    PlaywrightEngine,
    PlaywrightLease,
    PlaywrightMode,
    WsVersionRiskLevel,
)
from nonebot_plugin_htmlrender.providers.sdk import ProviderAvailability
from nonebot_plugin_htmlrender.rendering.observers import NoopOperationObserver

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser, Playwright
    from pytest_mock import MockerFixture


def _engine(**settings: object) -> PlaywrightEngine:
    return PlaywrightEngine(
        PlaywrightConfig.model_validate(settings),
        operation_observer=NoopOperationObserver(),
    )


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, PlaywrightMode.LOCAL),
        ({"connect_ws": {"endpoint": "ws://host/browser"}}, PlaywrightMode.REMOTE_WS),
        (
            {"connect_cdp": {"endpoint": "http://host:9222"}},
            PlaywrightMode.REMOTE_CDP,
        ),
    ],
)
def test_resolve_mode_uses_injected_settings(
    settings: dict[str, object],
    expected: PlaywrightMode,
) -> None:
    assert _engine(**settings)._resolve_mode() is expected


def test_proxy_and_url_helpers() -> None:
    assert PlaywrightEngine._build_proxy("http://proxy:7890") == {
        "server": "http://proxy:7890"
    }
    assert PlaywrightEngine._build_proxy(
        "http://proxy:7890",
        "localhost",
    ) == {"server": "http://proxy:7890", "bypass": "localhost"}


async def test_create_browser_remote_cdp_uses_configured_endpoint(
    mocker: MockerFixture,
) -> None:
    browser = object()
    chromium = mocker.Mock()
    chromium.connect_over_cdp = mocker.AsyncMock(return_value=browser)
    playwright = SimpleNamespace(chromium=chromium)
    engine = _engine(connect_cdp={"endpoint": "http://host:9222"})

    result = await engine._create_browser(
        cast("Playwright", playwright),
        PlaywrightMode.REMOTE_CDP,
    )

    assert result is browser
    chromium.connect_over_cdp.assert_awaited_once_with("http://host:9222")


async def test_create_browser_remote_ws_runs_version_gate(
    mocker: MockerFixture,
) -> None:
    browser = object()
    chromium = mocker.Mock()
    chromium.connect = mocker.AsyncMock(return_value=browser)
    playwright = SimpleNamespace(chromium=chromium)
    engine = _engine(connect_ws={"endpoint": "ws://host/browser"})
    gate = mocker.patch.object(
        engine,
        "_check_ws_version_gate",
        new=mocker.AsyncMock(),
    )

    result = await engine._create_browser(
        cast("Playwright", playwright),
        PlaywrightMode.REMOTE_WS,
    )

    assert result is browser
    gate.assert_awaited_once_with("ws://host/browser")
    chromium.connect.assert_awaited_once_with(endpoint="ws://host/browser")


async def test_create_browser_local_applies_launch_settings(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "chromium"
    executable.write_text("browser", encoding="utf-8")
    browser = object()
    chromium = mocker.Mock()
    chromium.launch = mocker.AsyncMock(return_value=browser)
    playwright = SimpleNamespace(chromium=chromium)
    engine = _engine(
        channel="chrome",
        proxy_server="http://proxy:7890",
        proxy_bypass="localhost",
        launch_args="--no-sandbox --disable-gpu",
        executable_path=executable,
    )

    result = await engine._create_browser(
        cast("Playwright", playwright),
        PlaywrightMode.LOCAL,
    )

    assert result is browser
    chromium.launch.assert_awaited_once_with(
        channel="chrome",
        proxy={"server": "http://proxy:7890", "bypass": "localhost"},
        args=["--no-sandbox", "--disable-gpu"],
        executable_path=str(executable),
    )


async def test_create_browser_local_delegates_environment_check(
    mocker: MockerFixture,
) -> None:
    playwright = cast("Playwright", SimpleNamespace(chromium=object()))
    engine = _engine()
    check = mocker.patch.object(
        engine,
        "_launch_local_browser",
        new=mocker.AsyncMock(return_value="browser"),
    )

    result = await engine._create_browser(playwright, PlaywrightMode.LOCAL)

    assert result == "browser"
    check.assert_awaited_once_with(playwright)


async def test_install_required_launch_honors_skip_setting(
    mocker: MockerFixture,
) -> None:
    engine = _engine(skip_browser_install=True)
    chromium = mocker.Mock()
    chromium.launch = mocker.AsyncMock(
        side_effect=RuntimeError("Executable doesn't exist at /browsers/chromium"),
    )
    playwright = cast("Playwright", SimpleNamespace(chromium=chromium))
    install = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.install_browser",
        new=mocker.AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="install_required"):
        await engine._launch_local_browser(playwright)
    chromium.launch.assert_awaited_once()
    install.assert_not_awaited()


async def test_install_required_launch_installs_once_and_retries_once(
    mocker: MockerFixture,
) -> None:
    config = PlaywrightConfig()
    engine = PlaywrightEngine(
        config,
        operation_observer=NoopOperationObserver(),
    )
    browser = object()
    chromium = mocker.Mock()
    chromium.launch = mocker.AsyncMock(
        side_effect=[
            RuntimeError("Executable doesn't exist at /browsers/chromium"),
            browser,
        ],
    )
    playwright = cast("Playwright", SimpleNamespace(chromium=chromium))
    install = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.install_browser",
        new=mocker.AsyncMock(),
    )

    result = await engine._launch_local_browser(playwright)

    assert result is browser
    assert chromium.launch.await_count == 2
    install.assert_awaited_once()
    assert install.await_args is not None
    assert install.await_args.args[0] == config


async def test_configuration_launch_failure_never_installs(
    mocker: MockerFixture,
) -> None:
    engine = _engine()
    chromium = mocker.Mock()
    chromium.launch = mocker.AsyncMock(
        side_effect=RuntimeError("Unknown launch option: bogus"),
    )
    playwright = cast("Playwright", SimpleNamespace(chromium=chromium))
    install = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.install_browser",
        new=mocker.AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="configuration"):
        await engine._launch_local_browser(playwright)
    chromium.launch.assert_awaited_once()
    install.assert_not_awaited()


def test_semver_and_endpoint_helpers() -> None:
    assert PlaywrightEngine._parse_semver("v1.55.3") == (1, 55, 3)
    assert PlaywrightEngine._parse_semver("unknown") is None
    assert (
        PlaywrightEngine._evaluate_ws_version_risk((1, 55, 3), (1, 55, 9))
        is WsVersionRiskLevel.SAFE
    )
    assert (
        PlaywrightEngine._evaluate_ws_version_risk((1, 55, 3), (1, 56, 0))
        is WsVersionRiskLevel.WARNING
    )
    assert (
        PlaywrightEngine._evaluate_ws_version_risk((1, 55, 3), (2, 0, 0))
        is WsVersionRiskLevel.BLOCK
    )
    assert PlaywrightEngine._extract_version_from_endpoint(
        "ws://host/browser?playwright_version=1.55.2"
    ) == (1, 55, 2)


async def test_ws_version_gate_warns_when_remote_version_is_unknown(
    mocker: MockerFixture,
) -> None:
    engine = _engine(connect_ws={"endpoint": "ws://host/browser"})
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.pkg_version",
        return_value="1.55.0",
    )
    mocker.patch.object(
        engine,
        "_detect_remote_ws_version",
        new=mocker.AsyncMock(return_value=None),
    )
    warning = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.logger.warning"
    )

    await engine._check_ws_version_gate()

    warning.assert_called_once()


@pytest.mark.parametrize(
    ("settings", "available", "reason"),
    [
        (
            {"connect_cdp": {"endpoint": "not-a-url"}},
            False,
            "CDP endpoint is invalid",
        ),
        (
            {"connect_ws": {"endpoint": "http://host/browser"}},
            False,
            "WebSocket endpoint is invalid",
        ),
        ({"skip_browser_install": False}, True, None),
    ],
)
def test_availability_remote_and_install_branches(
    mocker: MockerFixture,
    settings: dict[str, object],
    available: bool,  # noqa: FBT001 -- pytest parameter
    reason: str | None,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.availability.find_spec",
        return_value=object(),
    )

    result = playwright_availability(PlaywrightConfig.model_validate(settings))

    assert result.available is available
    if reason is not None:
        assert reason in (result.reason or "")


def test_availability_checks_explicit_executable(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.availability.find_spec",
        return_value=object(),
    )
    executable = tmp_path / "chromium"
    missing = playwright_availability(PlaywrightConfig(executable_path=executable))
    executable.write_text("browser", encoding="utf-8")
    present = playwright_availability(PlaywrightConfig(executable_path=executable))

    assert missing.available is False
    assert present == ProviderAvailability(available=True)


def test_availability_checks_injected_storage_path(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.availability.find_spec",
        return_value=object(),
    )
    installed = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install_state.has_installed_browser",
        return_value=False,
    )
    storage_path = tmp_path / "playwright-test"
    config = PlaywrightConfig(
        engine=BrowserEngine.FIREFOX,
        skip_browser_install=True,
        storage_path=storage_path,
    )

    result = playwright_availability(config)

    assert result.available is False
    installed.assert_called_once_with(
        BrowserEngine.FIREFOX,
        storage_path=storage_path,
    )


async def test_create_and_close_lease_owns_process_and_browser(
    mocker: MockerFixture,
) -> None:
    config = PlaywrightConfig()
    engine = PlaywrightEngine(
        config,
        operation_observer=NoopOperationObserver(),
    )
    playwright = mocker.Mock()
    playwright.stop = mocker.AsyncMock()
    browser = mocker.Mock()
    browser.is_connected.return_value = True
    browser.close = mocker.AsyncMock()
    starter = mocker.Mock()
    starter.start = mocker.AsyncMock(return_value=playwright)
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.async_playwright",
        return_value=starter,
    )
    mocker.patch.object(
        engine,
        "_create_browser",
        new=mocker.AsyncMock(return_value=browser),
    )
    scope = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.spawn.browsers_path_scope"
    )
    reconcile = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.reconcile_legacy_playwright_cache"
    )
    record = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.record_playwright_runtime_state"
    )

    lease = await engine.create_lease()
    await engine.close_lease(lease)

    assert lease.playwright is playwright
    assert lease.browser is browser
    scope.assert_called_once()
    reconcile.assert_called_once()
    record.assert_called_once()
    browser.close.assert_awaited_once_with()
    playwright.stop.assert_awaited_once_with()


async def test_create_lease_cleans_process_when_browser_creation_fails(
    mocker: MockerFixture,
) -> None:
    engine = _engine()
    playwright = mocker.Mock()
    playwright.stop = mocker.AsyncMock()
    starter = mocker.Mock()
    starter.start = mocker.AsyncMock(return_value=playwright)
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.async_playwright",
        return_value=starter,
    )
    mocker.patch.object(
        engine,
        "_create_browser",
        new=mocker.AsyncMock(side_effect=RuntimeError("launch failed")),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.spawn.browsers_path_scope"
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.reconcile_legacy_playwright_cache"
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.record_playwright_runtime_state"
    )

    with pytest.raises(RuntimeError, match="launch failed"):
        await engine.create_lease()

    playwright.stop.assert_awaited_once_with()


async def test_close_lease_aggregates_browser_and_driver_failures(
    mocker: MockerFixture,
) -> None:
    config = PlaywrightConfig()
    engine = PlaywrightEngine(
        config,
        operation_observer=NoopOperationObserver(),
    )
    playwright = mocker.Mock()
    playwright.stop = mocker.AsyncMock(side_effect=RuntimeError("stop failed"))
    browser = mocker.Mock()
    browser.is_connected.return_value = True
    browser.close = mocker.AsyncMock(side_effect=RuntimeError("close failed"))
    lease = PlaywrightLease(
        playwright=playwright,
        browser=browser,
        mode=PlaywrightMode.LOCAL,
    )

    with pytest.raises(BaseExceptionGroup) as info:
        await engine.close_lease(lease)

    messages = sorted(str(error) for error in info.value.exceptions)
    assert messages == ["close failed", "stop failed"]
    browser.close.assert_awaited_once_with()
    playwright.stop.assert_awaited_once_with()


async def test_create_lease_failure_aggregates_driver_stop_failure(
    mocker: MockerFixture,
) -> None:
    engine = _engine()
    playwright = mocker.Mock()
    playwright.stop = mocker.AsyncMock(side_effect=RuntimeError("stop failed"))
    starter = mocker.Mock()
    starter.start = mocker.AsyncMock(return_value=playwright)
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.async_playwright",
        return_value=starter,
    )
    mocker.patch.object(
        engine,
        "_create_browser",
        new=mocker.AsyncMock(side_effect=RuntimeError("launch failed")),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.spawn.browsers_path_scope"
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.reconcile_legacy_playwright_cache"
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.record_playwright_runtime_state"
    )

    with pytest.raises(BaseExceptionGroup) as info:
        await engine.create_lease()

    messages = sorted(str(error) for error in info.value.exceptions)
    assert messages == ["launch failed", "stop failed"]


async def test_create_lease_propagates_preparation_failure(
    mocker: MockerFixture,
) -> None:
    engine = _engine()
    reconcile = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.reconcile_legacy_playwright_cache",
        side_effect=RuntimeError("cache reconciliation failed"),
    )
    starter = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.async_playwright"
    )

    with pytest.raises(RuntimeError, match="cache reconciliation failed"):
        await engine.create_lease()

    reconcile.assert_called_once()
    starter.assert_not_called()


def test_lease_liveness_is_browser_connection(mocker: MockerFixture) -> None:
    engine = _engine()
    browser = mocker.Mock()
    browser.is_connected.side_effect = [True, False]
    lease = PlaywrightLease(
        playwright=cast("Playwright", object()),
        browser=cast("Browser", browser),
        mode=PlaywrightMode.LOCAL,
    )

    assert engine.is_alive(lease) is True
    assert engine.is_alive(lease) is False


def test_channel_candidates_cover_supported_chromium_channels() -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.availability import (  # noqa: PLC0415
        _channel_command_candidates,
    )

    assert "google-chrome" in _channel_command_candidates(ChromiumChannel.CHROME.value)
