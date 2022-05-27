import pytest
from nonebug import App


@pytest.mark.asyncio
async def test_text_to_pic(app: App):
    from nonebot_plugin_htmlrender import text_to_pic

    img = await text_to_pic("114514")
    assert isinstance(img, bytes)


@pytest.mark.asyncio
async def test_md_to_pic(app: App):
    from nonebot_plugin_htmlrender import md_to_pic

    img = await md_to_pic("$$114514$$")
    assert isinstance(img, bytes)


@pytest.mark.asyncio
async def html_to_pic(app: App):
    from nonebot_plugin_htmlrender import html_to_pic

    img = await html_to_pic("<html><body><p>114514</p></body></html>")
    assert isinstance(img, bytes)
