import pytest
from nonebug import App


@pytest.mark.asyncio
async def test_text_to_pic(app: App):
    from nonebot_plugin_htmlrender import text_to_pic

    async with app.test_server():
        img = await text_to_pic("114514")
        assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_md_to_pic(app: App):
    from nonebot_plugin_htmlrender import md_to_pic

    async with app.test_server():
        img = await md_to_pic("$$114514$$")
        assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_html_to_pic(app: App):
    from nonebot_plugin_htmlrender import html_to_pic

    async with app.test_server():
        img = await html_to_pic("<html><body><p>114514</p></body></html>")
        assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_template_to_pic(app: App):
    from nonebot_plugin_htmlrender import template_to_pic

    from pathlib import Path

    text_list = ["1", "2", "3", "4"]
    template_path = str(Path(__file__).parent / "templates")
    template_name = "text.html"

    async with app.test_server():
        img = await template_to_pic(
            template_path=template_path,
            template_name=template_name,
            templates={"text_list": text_list},
            pages={
                "viewport": {"width": 600, "height": 300},
                "base_url": f"file://{template_path}",
            },
            wait=2,
        )
        assert isinstance(img, bytes)
