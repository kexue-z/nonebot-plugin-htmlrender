from io import BytesIO
from pathlib import Path
from typing import Any

from nonebug import App
from PIL import Image, ImageChops
import pytest


@pytest.fixture
async def browser():
    """启动和关闭浏览器的 fixture"""
    from nonebot_plugin_htmlrender import shutdown_browser, start_browser

    await start_browser()
    yield
    await shutdown_browser()


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
    template_path = str(Path(__file__).parent / "templates")

    template_type = getattr(request, "param", "progress")

    if template_type == "progress":
        template_name = "progress.html.jinja2"
        data_list = ["1", "2", "3", "4"]
    elif template_type == "text":
        template_name = "text.html"
        data_list = ["1", "2", "3", "4"]
    else:
        raise ValueError(f"Unsupported template type: {template_type}")

    return template_path, template_name, data_list


@pytest.fixture
def test_image() -> Image.Image:
    """测试图片的 fixture"""
    test_image_path = Path(__file__).parent / "resources" / "test_template_filter.png"
    return Image.open(test_image_path)


@pytest.mark.asyncio
async def test_text_to_pic(app: App, browser: None) -> None:
    """测试文本转图片功能"""
    from nonebot_plugin_htmlrender import text_to_pic

    img = await text_to_pic("114514")
    assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_md_to_pic(app: App, browser: None) -> None:
    """测试 Markdown 转图片功能"""
    from nonebot_plugin_htmlrender import md_to_pic

    img = await md_to_pic("$$114514$$")
    assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_html_to_pic(app: App, browser: None) -> None:
    """测试 HTML 转图片功能"""
    from nonebot_plugin_htmlrender import html_to_pic

    img = await html_to_pic("<html><body><p>114514</p></body></html>")
    assert isinstance(img, bytes)


@pytest.mark.asyncio
@pytest.mark.parametrize("template_resources", ["text"], indirect=True)
async def test_template_to_pic(
    app: App,
    browser: None,
    page_config: dict[str, Any],
    template_resources: tuple[str, str, list[str]],
) -> None:
    """测试模板转图片功能"""
    from nonebot_plugin_htmlrender import template_to_pic

    template_path, template_name, text_list = template_resources
    page_config["base_url"] = f"file://{template_path}"

    img = await template_to_pic(
        template_path=template_path,
        template_name=template_name,
        templates={"text_list": text_list},
        pages=page_config,
    )
    assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_template_filter(
    app: App,
    browser: None,
    template_resources: tuple[str, str, list[str]],
    test_image: Image.Image,
    page_config: dict[str, Any],
) -> None:
    """测试模板过滤器功能"""
    from nonebot_plugin_htmlrender import template_to_pic

    def _count_to_color(count: str) -> str:
        if count == "1":
            return "#facc15"
        elif count == "2":
            return "#f87171"
        elif count == "3":
            return "#c084fc"
        else:
            return "#60a5fa"

    template_path, template_name, count_list = template_resources
    page_config["base_url"] = f"file://{template_path}"

    image_byte = await template_to_pic(
        template_path=template_path,
        template_name=template_name,
        templates={"counts": count_list},
        filters={"count_to_color": _count_to_color},
        pages=page_config,
    )

    image = Image.open(BytesIO(initial_bytes=image_byte))
    diff = ImageChops.difference(image, test_image)
    assert diff.getbbox() is None
