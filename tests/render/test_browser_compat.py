from importlib import import_module
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from playwright.async_api import Browser, Page
import pytest
from pytest_mock import MockerFixture

_UNIT_TEST_PLAYWRIGHT_PATH = (
    Path(__file__).resolve().parents[1] / ".artifacts" / "playwright-browsers-unit"
)


@pytest.fixture
def mock_browser(mocker: MockerFixture) -> Browser:
    browser = mocker.AsyncMock(spec=Browser)
    browser.is_connected.return_value = True
    browser.close = mocker.AsyncMock()
    return browser


@pytest.fixture
def mock_page(mocker: MockerFixture) -> AsyncMock:
    page = mocker.AsyncMock(spec=Page)
    page.close = mocker.AsyncMock()
    return page


@pytest.mark.anyio
@pytest.mark.parametrize(
    "exception",
    [Exception("Test error"), ValueError("Test value error")],
    ids=["exception", "value_error"],
)
async def test_suppress_and_log(mocker: MockerFixture, exception: Exception) -> None:
    from nonebot_plugin_htmlrender.utils import suppress_and_log  # noqa: PLC0415

    mock_logger = mocker.patch("nonebot_plugin_htmlrender.utils.logger")

    with suppress_and_log():
        raise exception

    mock_logger.opt.assert_called_once_with(exception=exception)
    mock_logger.opt().warning.assert_called_once()


@pytest.mark.anyio
async def test_get_new_page_delegates_to_render_context(
    mocker: MockerFixture,
    mock_page: AsyncMock,
) -> None:
    from nonebot_plugin_htmlrender.browser import get_new_page  # noqa: PLC0415

    mock_cm = mocker.MagicMock()
    mock_cm.__aenter__ = mocker.AsyncMock(return_value=mock_page)
    mock_cm.__aexit__ = mocker.AsyncMock(return_value=None)

    get_render_context_mock = mocker.patch(
        "nonebot_plugin_htmlrender._compat.get_render_context",
        return_value=mock_cm,
    )

    async with get_new_page(viewport={"width": 800, "height": 600}) as page:
        assert page == mock_page

    get_render_context_mock.assert_called_once_with(
        device_scale_factor=2,
        viewport={"width": 800, "height": 600},
    )


@pytest.mark.anyio
async def test_get_browser_returns_browser(
    mocker: MockerFixture,
    mock_browser: Browser,
) -> None:
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        get_browser,
    )

    session = SimpleNamespace(handle=mock_browser)
    get_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender._compat.get_render",
        return_value=session,
    )

    browser = await get_browser(headless=True)

    assert browser == mock_browser
    get_render_mock.assert_called_once_with(headless=True)


@pytest.mark.anyio
async def test_get_browser_rejects_non_browser_target(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        get_browser,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender._compat.get_render",
        return_value=SimpleNamespace(handle=object()),
    )

    with pytest.raises(RuntimeError, match="not a Browser instance"):
        await get_browser()


@pytest.mark.anyio
async def test_startup_htmlrender_returns_browser(
    mocker: MockerFixture,
    mock_browser: Browser,
) -> None:
    from nonebot_plugin_htmlrender.browser import startup_htmlrender  # noqa: I001, PLC0415

    session = SimpleNamespace(handle=mock_browser)
    startup_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender._compat.startup_render",
        return_value=session,
    )

    browser = await startup_htmlrender(slow_mo=50)

    assert browser == mock_browser
    startup_render_mock.assert_called_once_with(slow_mo=50)


@pytest.mark.anyio
async def test_launch_delegates_to_startup_render(
    mocker: MockerFixture,
    mock_browser: Browser,
) -> None:
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        _launch,
    )

    startup_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender._compat.startup_render",
        return_value=SimpleNamespace(handle=mock_browser),
    )

    browser = await _launch("chromium", headless=True)

    assert browser == mock_browser
    startup_render_mock.assert_called_once_with(headless=True)


@pytest.mark.anyio
async def test_shutdown_htmlrender_delegates_to_shutdown_render(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.browser import shutdown_htmlrender  # noqa: I001, PLC0415

    shutdown_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender._compat.shutdown_render",
        new=mocker.AsyncMock(),
    )

    await shutdown_htmlrender()

    shutdown_render_mock.assert_awaited_once_with()


@pytest.mark.anyio
async def test_plugin_init_prewarms_filehost_for_playwright_backend(
    mocker: MockerFixture,
) -> None:
    import nonebot_plugin_htmlrender as plugin  # noqa: PLC0415
    from nonebot_plugin_htmlrender.consts import RenderBackend  # noqa: PLC0415
    filehost_runtime = import_module(
        "nonebot_plugin_htmlrender.resources.filehost"
    )

    prewarm_mock = mocker.patch.object(
        filehost_runtime,
        "ensure_filehost_runtime_ready",
        new=mocker.AsyncMock(return_value=True),
    )
    prepare_mock = mocker.patch.object(plugin, "_prepare_playwright_startup")
    startup_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender.startup_render",
        new=mocker.AsyncMock(),
    )
    mocker.patch.object(
        plugin.plugin_config, "render_backend", RenderBackend.PLAYWRIGHT
    )
    mocker.patch.object(plugin.plugin_config, "render_startup_mode", new="warmup")

    await plugin.init()

    prepare_mock.assert_called_once_with()
    prewarm_mock.assert_awaited_once_with(reason="plugin_startup")
    startup_render_mock.assert_awaited_once_with()


@pytest.mark.anyio
async def test_plugin_init_skips_filehost_prewarm_for_non_playwright_backend(
    mocker: MockerFixture,
) -> None:
    import nonebot_plugin_htmlrender as plugin  # noqa: PLC0415
    from nonebot_plugin_htmlrender.consts import RenderBackend  # noqa: PLC0415

    prepare_mock = mocker.patch.object(plugin, "_prepare_playwright_startup")
    startup_render_mock = mocker.patch(
        "nonebot_plugin_htmlrender.startup_render",
        new=mocker.AsyncMock(),
    )
    mocker.patch.object(plugin.plugin_config, "render_backend", RenderBackend.SKIA)
    mocker.patch.object(plugin.plugin_config, "render_startup_mode", new="off")

    await plugin.init()

    prepare_mock.assert_not_called()
    startup_render_mock.assert_not_awaited()


def test_prepare_and_clear_playwright_env_vars(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import runtime  # noqa: PLC0415

    storage_path = _UNIT_TEST_PLAYWRIGHT_PATH
    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

    mocker.patch.object(runtime.plugin_config, "render_storage_path", storage_path)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.get_playwright_config",
        return_value=SimpleNamespace(executable_path=None),
    )

    runtime.prepare_playwright_env_vars()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(storage_path)

    runtime.clear_playwright_env_vars()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_prepare_playwright_env_vars_skips_custom_executable(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import runtime  # noqa: PLC0415

    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    mocker.patch.object(
        runtime.plugin_config,
        "render_storage_path",
        _UNIT_TEST_PLAYWRIGHT_PATH,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.get_playwright_config",
        return_value=SimpleNamespace(executable_path=Path("/custom/chromium")),
    )

    runtime.prepare_playwright_env_vars()

    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


@pytest.mark.parametrize(
    ("system_name", "expected_path"),
    [
        ("Windows", Path.home() / "AppData" / "Local" / "ms-playwright"),
        ("Darwin", Path.home() / "Library" / "Caches" / "ms-playwright"),
        ("Linux", Path.home() / ".cache" / "ms-playwright"),
    ],
    ids=["windows", "macos", "linux"],
)
def test_clean_playwright_cache(
    mocker: MockerFixture,
    system_name: str,
    expected_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.runtime import (  # noqa: PLC0415
        reconcile_legacy_playwright_cache,
    )

    storage_path = expected_path.parent / "current-storage"
    mocker.patch("platform.system", return_value=system_name)
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.get_playwright_storage_path",
        return_value=storage_path,
    )
    mocker.patch.object(Path, "exists", return_value=True)
    mock_rmtree = mocker.patch("shutil.rmtree")

    reconcile_legacy_playwright_cache(cleanup=True)

    mock_rmtree.assert_called_once_with(str(expected_path))


def test_clean_playwright_cache_path_not_exists(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.runtime import (  # noqa: PLC0415
        reconcile_legacy_playwright_cache,
    )

    storage_path = Path.cwd() / ".artifacts" / "current-storage"
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.get_playwright_storage_path",
        return_value=storage_path,
    )
    mocker.patch.object(Path, "exists", return_value=False)
    mock_rmtree = mocker.patch("shutil.rmtree")

    reconcile_legacy_playwright_cache(cleanup=False)

    mock_rmtree.assert_not_called()


def test_clean_playwright_cache_with_error(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright.runtime import (  # noqa: PLC0415
        reconcile_legacy_playwright_cache,
    )

    storage_path = Path.home() / ".cache" / "htmlrender-test-storage"
    mocker.patch("platform.system", return_value="Linux")
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.get_playwright_storage_path",
        return_value=storage_path,
    )
    mocker.patch.object(Path, "exists", return_value=True)
    mocker.patch("shutil.rmtree", side_effect=PermissionError())
    mock_logger_error = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.runtime.logger.error"
    )

    reconcile_legacy_playwright_cache(cleanup=True)

    mock_logger_error.assert_called_once()
