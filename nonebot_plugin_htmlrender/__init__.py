import nonebot
from nonebot.log import logger
from nonebot.plugin import export

from .browser import get_browser, shutdown_browser, get_new_page
from .date_source import (
    text_to_pic,
    md_to_pic,
    template_to_html,
    html_to_pic,
    template_to_pic,
    capture_element,
)

driver = nonebot.get_driver()
config = driver.config
export = export()


@driver.on_startup
async def init(**kwargs):
    """Start Browser

    Returns:
        Browser: Browser
    """
    browser = await get_browser(**kwargs)
    logger.info("Browser Started.")
    return browser


@driver.on_shutdown
async def shutdown():
    await shutdown_browser()
    logger.info("Browser Stoped.")


browser_init = init

export.browser = init
export.text_to_pic = text_to_pic
export.get_new_page = get_new_page
export.md_to_pic = md_to_pic
export.template_to_html = template_to_html
export.template_to_pic = template_to_pic
export.html_to_pic = html_to_pic
export.capture_element = capture_element


all = [
    "browser_init",
    "text_to_pic",
    "get_new_page",
    "md_to_pic",
    "template_to_html",
    "template_to_pic",
    "html_to_pic",
    "capture_element",
]
