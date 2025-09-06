from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock

from playwright.async_api import Browser, Page
import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def mock_browser(mocker: MockerFixture) -> Browser:
    """模拟的浏览器实例 fixture"""
    browser = mocker.AsyncMock(spec=Browser)
    browser.is_connected.return_value = True
    browser.close = mocker.AsyncMock()
    return browser


@pytest.fixture
def mock_page(mocker: MockerFixture) -> AsyncMock:
    """模拟的页面实例 fixture"""
    mock = mocker.AsyncMock(spec=Page)
    mock.close = mocker.AsyncMock()
    return mock


@pytest.fixture
async def mock_browser_context(
    mocker: MockerFixture, mock_browser: Browser
) -> AsyncGenerator[None, None]:
    """模拟浏览器上下文的 fixture"""
    mocker.patch("nonebot_plugin_htmlrender.browser._browser", mock_browser)
    yield
    mocker.patch("nonebot_plugin_htmlrender.browser._browser", None)


@pytest.fixture
def browser_config() -> dict[str, str]:
    """浏览器配置的 fixture"""
    return {
        "browser": "chromium",
        "cdp": "ws://localhost:9222",
        "pwp": "ws://localhost:3000/chromium/playwright",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception",
    [Exception("Test error"), ValueError("Test value error")],
    ids=["exception", "value_error"],
)
async def test_suppress_and_log(mocker: MockerFixture, exception: Exception) -> None:
    """测试 _suppress_and_log 异常抑制和日志记录"""
    from nonebot_plugin_htmlrender.utils import suppress_and_log

    mock_logger = mocker.patch("nonebot_plugin_htmlrender.utils.logger")

    with suppress_and_log():
        raise exception

    mock_logger.opt.assert_called_once_with(exception=exception)
    mock_logger.opt().warning.assert_called_once()


@pytest.mark.asyncio
async def test_launch(mocker: MockerFixture, browser_config: dict[str, str]) -> None:
    """测试浏览器启动"""
    from nonebot_plugin_htmlrender.browser import _launch

    mock_browser_type = mocker.AsyncMock()
    mock_playwright = mocker.MagicMock()
    setattr(mock_playwright, "chromium", mock_browser_type)

    mocker.patch("nonebot_plugin_htmlrender.browser._playwright", mock_playwright)
    await _launch(browser_config["browser"])

    mock_browser_type.launch.assert_called_once()


@pytest.mark.asyncio
async def test_init_browser_success(
    mocker: MockerFixture, mock_browser: Browser
) -> None:
    """测试浏览器初始化成功"""
    from nonebot_plugin_htmlrender.browser import startup_htmlrender

    browser = await startup_htmlrender()
    assert isinstance(browser, Browser)
    assert browser.is_connected()
    assert browser.browser_type.name == "chromium"
    await browser.close()


@pytest.mark.asyncio
async def test_get_new_page(
    mocker: MockerFixture,
    mock_browser: Browser,
    mock_page: AsyncMock,
) -> None:
    """测试获取新页面"""
    from nonebot_plugin_htmlrender.browser import get_new_page

    close_mock = mocker.AsyncMock()
    mock_page.close = close_mock
    mock_page.__aenter__.return_value = mock_page

    async def _aexit(*args):
        await mock_page.close()

    mock_page.__aexit__ = mocker.AsyncMock(side_effect=_aexit)

    new_page_mock = mocker.AsyncMock(return_value=mock_page)
    mocker.patch.object(mock_browser, "new_page", new_page_mock)

    mocker.patch(
        "nonebot_plugin_htmlrender.browser.get_browser",
        return_value=mock_browser,
    )

    async with get_new_page() as page:
        assert page == mock_page

    assert close_mock.call_count == 1


@pytest.mark.asyncio
async def test_get_browser_connected(
    mock_browser: Browser, mock_browser_context: None
) -> None:
    """测试获取已连接的浏览器"""
    from nonebot_plugin_htmlrender.browser import get_browser

    browser = await get_browser()
    assert browser == mock_browser


@pytest.mark.asyncio
async def test_shutdown_browser(
    mock_browser: Browser,
    mock_browser_context: None,
    mocker: MockerFixture,
) -> None:
    """测试关闭浏览器"""
    from nonebot_plugin_htmlrender.browser import shutdown_htmlrender

    close_mock = mocker.AsyncMock()
    mock_browser.close = close_mock

    await shutdown_htmlrender()
    assert close_mock.call_count == 1


@pytest.mark.asyncio
async def test_connect_via_cdp(
    mocker: MockerFixture, mock_browser: Browser, browser_config: dict[str, str]
) -> None:
    """测试通过CDP连接浏览器"""
    from nonebot_plugin_htmlrender.browser import startup_htmlrender

    mocker.patch(
        "nonebot_plugin_htmlrender.browser._connect_via_cdp", return_value=mock_browser
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_browser",
        browser_config["browser"],
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_connect_over_cdp",
        browser_config["cdp"],
    )

    browser = await startup_htmlrender()
    assert browser == mock_browser


@pytest.mark.asyncio
async def test_connect(
    mocker: MockerFixture, mock_browser: Browser, browser_config: dict[str, str]
) -> None:
    """测试通过Playwright协议连接浏览器"""
    from nonebot_plugin_htmlrender.browser import startup_htmlrender

    mocker.patch(
        "nonebot_plugin_htmlrender.browser._connect", return_value=mock_browser
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_browser",
        browser_config["browser"],
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_connect",
        browser_config["pwp"],
    )

    browser = await startup_htmlrender()
    assert browser == mock_browser


@pytest.mark.parametrize(
    ("proxy_url", "expected"),
    [
        (
            "http://user:pass@proxy.com:8080",
            {"server": "http://proxy.com:8080", "username": "user", "password": "pass"},
        ),
        ("http://proxy.com:8080", {"server": "http://proxy.com:8080"}),
    ],
    ids=["with_auth", "without_auth"],
)
def test_enhance_proxy_settings(proxy_url: str, expected: dict[str, str]) -> None:
    """测试代理设置基本功能"""
    from nonebot_plugin_htmlrender.utils import proxy_settings

    result = proxy_settings(proxy_url)
    assert result == expected


def test_enhance_proxy_settings_with_bypass(mocker: MockerFixture) -> None:
    """测试代理设置bypass功能"""
    from nonebot_plugin_htmlrender.utils import proxy_settings

    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_proxy_host_bypass",
        "localhost",
    )

    result = proxy_settings("http://proxy.com:8080")
    assert result == {"server": "http://proxy.com:8080", "bypass": "localhost"}


def test_enhance_proxy_settings_none() -> None:
    """测试空代理设置"""
    from nonebot_plugin_htmlrender.utils import proxy_settings

    result = proxy_settings(None)
    assert result is None


@pytest.mark.asyncio
async def test_start_browser_with_cdp(
    mocker: MockerFixture, browser_config: dict[str, str]
) -> None:
    """测试使用CDP启动浏览器"""
    from nonebot_plugin_htmlrender.browser import startup_htmlrender

    mock_cdp = mocker.patch(
        "nonebot_plugin_htmlrender.browser._connect_via_cdp",
        return_value=mocker.MagicMock(spec=Browser),
    )
    mocker.patch("playwright.async_api.async_playwright")
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_browser",
        browser_config["browser"],
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_connect_over_cdp",
        browser_config["cdp"],
    )

    await startup_htmlrender()
    mock_cdp.assert_called_once()


@pytest.mark.asyncio
async def test_start_browser_with_config(mocker: MockerFixture) -> None:
    """测试带配置启动浏览器"""
    from nonebot_plugin_htmlrender.browser import startup_htmlrender

    mock_launch = mocker.patch(
        "nonebot_plugin_htmlrender.browser._launch",
        return_value=mocker.MagicMock(spec=Browser),
    )
    mocker.patch("playwright.async_api.async_playwright")
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_browser_channel",
        "chrome-canary",
    )

    await startup_htmlrender()
    mock_launch.assert_called_with(mocker.ANY, channel="chrome-canary")

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
    mocker: MockerFixture, system_name: str, expected_path: Path
) -> None:
    """测试不同操作系统下的 Playwright 缓存清理"""
    from nonebot_plugin_htmlrender.browser import clean_playwright_cache

    mocker.patch("platform.system", return_value=system_name)
    mocker.patch.object(Path, "exists", return_value=True)
    mock_rmtree = mocker.patch("shutil.rmtree")

    clean_playwright_cache()

    mock_rmtree.assert_called_once_with(str(expected_path))

def test_clean_playwright_cache_path_not_exists(mocker: MockerFixture) -> None:
    """测试路径不存在时的 Playwright 缓存清理"""
    from nonebot_plugin_htmlrender.browser import clean_playwright_cache

    mocker.patch.object(Path, "exists", return_value=False)
    mock_rmtree = mocker.patch("shutil.rmtree")

    clean_playwright_cache()

    mock_rmtree.assert_not_called()

def test_clean_playwright_cache_with_error(mocker: MockerFixture) -> None:
    """测试清理过程中发生错误的情况"""
    from nonebot_plugin_htmlrender.browser import clean_playwright_cache

    mocker.patch("platform.system", return_value="Linux")
    mocker.patch.object(Path, "exists", return_value=True)
    mocker.patch("shutil.rmtree", side_effect=PermissionError())
    mock_logger_error = mocker.patch("nonebot_plugin_htmlrender.browser.logger.error")

    clean_playwright_cache()

    mock_logger_error.assert_called_once()
