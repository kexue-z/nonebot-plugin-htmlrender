from collections.abc import AsyncGenerator
from typing import cast

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
def mock_page(mocker: MockerFixture) -> Page:
    """模拟的页面实例 fixture"""
    mock = mocker.AsyncMock(spec=Page)
    mock.close = mocker.AsyncMock()
    return cast(Page, mock)


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
    mock_logger.opt().warning.assert_called_once_with("关闭 playwright 时发生错误。")


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
    from nonebot_plugin_htmlrender.browser import init_browser

    mock_start = mocker.patch(
        "nonebot_plugin_htmlrender.browser.start_browser",
        return_value=mock_browser,
    )

    browser = await init_browser()
    assert isinstance(browser, Browser)
    mock_start.assert_called_once()


@pytest.mark.asyncio
async def test_get_new_page(
    mocker: MockerFixture,
    mock_browser: Browser,
    mock_page: Page,
) -> None:
    """测试获取新页面"""
    from nonebot_plugin_htmlrender.browser import get_new_page

    close_mock = mocker.AsyncMock()
    mock_page.close = close_mock

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
    from nonebot_plugin_htmlrender.browser import shutdown_browser

    close_mock = mocker.AsyncMock()
    mock_browser.close = close_mock

    await shutdown_browser()
    assert close_mock.call_count == 1


@pytest.mark.asyncio
async def test_connect_via_cdp(
    mocker: MockerFixture, mock_browser: Browser, browser_config: dict[str, str]
) -> None:
    """测试通过CDP连接浏览器"""
    from nonebot_plugin_htmlrender.browser import start_browser

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

    browser = await start_browser()
    assert browser == mock_browser


@pytest.mark.asyncio
async def test_connect(
    mocker: MockerFixture, mock_browser: Browser, browser_config: dict[str, str]
) -> None:
    """测试通过Playwright协议连接浏览器"""
    from nonebot_plugin_htmlrender.browser import start_browser

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

    browser = await start_browser()
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
    from nonebot_plugin_htmlrender.browser import start_browser

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

    await start_browser()
    mock_cdp.assert_called_once()


@pytest.mark.asyncio
async def test_start_browser_with_config(mocker: MockerFixture) -> None:
    """测试带配置启动浏览器"""
    from nonebot_plugin_htmlrender.browser import start_browser

    mock_launch = mocker.patch(
        "nonebot_plugin_htmlrender.browser._launch",
        return_value=mocker.MagicMock(spec=Browser),
    )
    mocker.patch("playwright.async_api.async_playwright")
    mocker.patch(
        "nonebot_plugin_htmlrender.browser.plugin_config.htmlrender_browser_channel",
        "chrome-canary",
    )

    await start_browser()
    mock_launch.assert_called_with(mocker.ANY, channel="chrome-canary")
