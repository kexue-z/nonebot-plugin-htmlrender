import pytest
from PIL import Image
from nonebug import App


def save_pic(name, img: bytes):
    with open(f"./test/{name}.png", mode="wb") as f:
        f.write(img)


@pytest.mark.asyncio
async def test_text_to_pic(app: App):
    from nonebot_plugin_htmlrender import text_to_pic

    img = await text_to_pic("114514")
    assert isinstance(img, bytes)
    save_pic("test_text_to_pic", img)


@pytest.mark.asyncio
async def test_md_to_pic(app: App):
    from nonebot_plugin_htmlrender import md_to_pic

    img = await md_to_pic("$$114514$$")
    assert isinstance(img, bytes)
    save_pic("test_md_to_pic", img)


@pytest.mark.asyncio
async def test_md_to_pic_qrcode(app: App):
    from nonebot_plugin_htmlrender import md_to_pic

    img = await md_to_pic("$$114514$$", add_qr=True)
    assert isinstance(img, bytes)
    save_pic("test_md_to_pic_qrcode", img)


@pytest.mark.asyncio
async def test_html_to_pic(app: App):
    from nonebot_plugin_htmlrender import html_to_pic

    img = await html_to_pic("<html><body><p>114514</p></body></html>")
    assert isinstance(img, bytes)
    save_pic("html_to_pic", img)
