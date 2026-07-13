from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from playwright.async_api import Browser, Page
import pytest
from pytest_mock import MockerFixture


@pytest.fixture(scope="module")
async def shared_browser() -> AsyncIterator[Browser]:
    """整个模块复用同一个 Browser，具体渲染仍各自创建独立 page/context。"""
    from nonebot_plugin_htmlrender import (  # noqa: PLC0415
        shutdown_render,
        startup_render,
    )
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        get_browser,
    )

    await startup_render()
    browser = await get_browser()
    assert await get_browser() is browser
    try:
        yield browser
    finally:
        await shutdown_render()


@pytest.fixture
def page_config() -> dict[str, Any]:
    """页面配置的 fixture"""
    return {
        "viewport": {"width": 600, "height": 300},
        "base_url": None,
    }


@pytest.fixture
def template_resources(request: Any) -> tuple[str, str, list[str]]:
    """模板资源的 fixture"""
    template_path = str(Path(__file__).resolve().parents[1] / "templates")

    template_type = getattr(request, "param", "progress")

    if template_type == "progress":
        template_name = "progress.html.jinja2"
        data_list = ["1", "2", "3", "4"]
    elif template_type == "text":
        template_name = "text.html"
        data_list = ["1", "2", "3", "4"]
    else:  # pragma: no cover
        raise ValueError(f"Unsupported template type: {template_type}")

    return template_path, template_name, data_list


@pytest.fixture
def test_image() -> Image.Image:
    """测试图片的 fixture"""
    test_image_path = (
        Path(__file__).resolve().parents[1] / "resources" / "test_template_filter.png"
    )
    return Image.open(test_image_path)


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_startup_htmlrender_reuses_shared_browser(
    shared_browser: Browser,
) -> None:
    """测试浏览器初始化后会复用同一个 Browser 会话。"""
    from nonebot_plugin_htmlrender import get_default_render  # noqa: PLC0415
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        get_browser,
    )

    render = get_default_render()
    browser = await get_browser()

    assert browser is shared_browser
    assert browser.is_connected()
    assert render._session is not None
    assert render._runtime is not None


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_get_new_page_creates_isolated_page_contexts(
    shared_browser: Browser,
) -> None:
    """测试共享 Browser 下的 page/context 仍然彼此隔离。"""
    from nonebot_plugin_htmlrender import get_new_page  # noqa: PLC0415

    assert shared_browser.is_connected()

    async with get_new_page() as first_page:
        assert isinstance(first_page, Page)
        await first_page.set_content("<title>first</title><p>114514</p>")
        async with get_new_page() as second_page:
            assert isinstance(second_page, Page)
            await second_page.set_content("<title>second</title><p>1919810</p>")

            assert first_page is not second_page
            assert first_page.context != second_page.context
            assert await first_page.title() == "first"
            assert await second_page.title() == "second"


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_text_to_pic(shared_browser: Browser) -> None:
    """测试文本转图片功能"""
    from nonebot_plugin_htmlrender import render_text  # noqa: PLC0415

    assert shared_browser.is_connected()
    img = await render_text("114514")
    assert isinstance(img, bytes)


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_md_to_pic(shared_browser: Browser) -> None:
    """测试 Markdown 转图片功能"""
    from nonebot_plugin_htmlrender import render_markdown  # noqa: PLC0415

    assert shared_browser.is_connected()
    img = await render_markdown("# 114514\n\n**1919810**")
    assert isinstance(img, bytes)


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_html_to_pic(shared_browser: Browser) -> None:
    """测试 HTML 转图片功能"""
    from nonebot_plugin_htmlrender import render_html  # noqa: PLC0415

    assert shared_browser.is_connected()
    img = await render_html("<html><body><p>114514</p></body></html>")
    assert isinstance(img, bytes)


@pytest.mark.anyio
@pytest.mark.parametrize("template_resources", ["text"], indirect=True)
@pytest.mark.requires_browser
async def test_template_to_pic(
    shared_browser: Browser,
    page_config: dict[str, Any],
    template_resources: tuple[str, str, list[str]],
) -> None:
    """测试模板转图片功能"""
    from nonebot_plugin_htmlrender import render_template  # noqa: PLC0415

    assert shared_browser.is_connected()
    template_path, template_name, text_list = template_resources
    page_config["base_url"] = f"file://{template_path}"

    img = await render_template(
        template_path,
        template_name=template_name,
        templates={"text_list": text_list},
        pages=page_config,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )
    assert isinstance(img, bytes)


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_template_filter(
    shared_browser: Browser,
    template_resources: tuple[str, str, list[str]],
    test_image: Image.Image,
    page_config: dict[str, Any],
) -> None:
    """测试模板过滤器功能"""
    from nonebot_plugin_htmlrender import render_template  # noqa: PLC0415

    assert shared_browser.is_connected()

    def _count_to_color(count: str) -> str:
        if count == "1":
            return "#facc15"
        if count == "2":
            return "#f87171"
        if count == "3":
            return "#c084fc"
        return "#60a5fa"

    template_path, template_name, count_list = template_resources
    page_config["base_url"] = f"file://{template_path}"

    image_byte = await render_template(
        template_path,
        template_name=template_name,
        templates={"counts": count_list},
        filters={"count_to_color": _count_to_color},
        pages=page_config,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    image = Image.open(BytesIO(image_byte))
    diff = ImageChops.difference(image, test_image)
    assert diff.getbbox() is None


@pytest.mark.anyio
async def test_render_markdown_injects_math_assets(mocker: MockerFixture) -> None:
    """测试包含数学公式时会注入 KaTeX 资源"""
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        render_markdown,
    )

    render_html_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.render_html",
        new=mocker.AsyncMock(return_value=b"rendered"),
    )

    result = await render_markdown("$$114514$$", session=object())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]

    assert result == b"rendered"
    assert render_html_mock.await_args is not None
    render_request = render_html_mock.await_args.args[0]
    assert "math/tex; mode=display" in render_request.content.html
    assert ".katex" in render_request.content.html
    assert "document.body.getElementsByTagName" in render_request.content.html
    assert "inline-equation" in render_request.content.html
    assert "<script defer>" in render_request.content.html
    assert "&lt;script" not in render_request.content.html


@pytest.mark.anyio
async def test_capture_element(mocker: MockerFixture) -> None:
    """测试网页元素捕获功能"""
    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        capture_html_element,
    )

    mock_screenshot = b"test_image_bytes"

    mock_locator = mocker.AsyncMock()
    mock_locator.screenshot.return_value = mock_screenshot

    mock_page = mocker.AsyncMock()
    mock_page.goto = mocker.AsyncMock()
    mock_page.on = mocker.MagicMock()
    mock_page.off = mocker.MagicMock()
    mock_page.locator = mocker.MagicMock(return_value=mock_locator)

    mock_cm = mocker.MagicMock()
    mock_cm.__aenter__ = mocker.AsyncMock(return_value=mock_page)
    mock_cm.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=mock_cm,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.log_page_telemetry",
        new=mocker.AsyncMock(),
    )

    result = await capture_html_element("https://example.com", "#target-element")

    assert result == mock_screenshot
    mock_page.goto.assert_called_once_with("https://example.com")
    mock_page.locator.assert_called_once_with("#target-element")
    mock_locator.screenshot.assert_called_once_with()

    mock_page.goto.reset_mock()
    mock_page.locator.reset_mock()
    mock_locator.screenshot.reset_mock()

    page_kwargs = {"device_scale_factor": 2.0}
    goto_kwargs = {"timeout": 5000}
    screenshot_kwargs = {"type": "jpeg", "quality": 80}

    result = await capture_html_element(
        "https://example.com",
        "//div[@id='xpath-element']",
        page_kwargs=page_kwargs,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        goto_kwargs=goto_kwargs,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        screenshot_kwargs=screenshot_kwargs,  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    )

    assert result == mock_screenshot
    mock_page.goto.assert_called_once_with("https://example.com", timeout=5000)
    mock_page.locator.assert_called_once_with("//div[@id='xpath-element']")
    mock_locator.screenshot.assert_called_once_with(type="jpeg", quality=80)


@pytest.mark.anyio
async def test_capture_element_exceptions_propagate(mocker: MockerFixture) -> None:
    """测试网页元素捕获时的异常能正确传递"""
    from playwright.async_api import Error  # noqa: PLC0415

    from nonebot_plugin_htmlrender.backend.playwright.operations import (  # noqa: PLC0415
        capture_html_element,
    )

    mock_cm = mocker.MagicMock()
    mock_cm.__aenter__ = mocker.AsyncMock(side_effect=Error("Browser error"))

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.operations.open_page_context",
        return_value=mock_cm,
    )

    with pytest.raises(Error) as exc_info:
        await capture_html_element("https://example.com", "#element")

    assert "Browser error" in str(exc_info.value)


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_shutdown_htmlrender_releases_shared_browser(
    shared_browser: Browser,
) -> None:
    """测试关闭时会清理默认渲染状态并断开共享 Browser。"""
    from nonebot_plugin_htmlrender import (  # noqa: PLC0415
        get_default_render,
        shutdown_render,
    )

    render = get_default_render()
    assert render._session is not None
    assert render._runtime is not None

    await shutdown_render()

    assert render._session is None
    assert render._runtime is None
    assert not shared_browser.is_connected()


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_startup_htmlrender_can_restart_after_shutdown() -> None:
    """测试关闭后仍可重新拉起 Browser。"""
    from nonebot_plugin_htmlrender import (  # noqa: PLC0415
        shutdown_render,
        startup_render,
    )
    from nonebot_plugin_htmlrender.browser import (  # noqa: PLC0415
        get_browser,
    )

    await startup_render()
    browser = await get_browser()

    assert browser.is_connected()
    assert await get_browser() is browser

    await shutdown_render()
