import nonebot
from nonebot.log import logger

from .browser import get_browser, get_new_page, shutdown_browser
from .date_source import (
    md_to_pic,
    html_to_pic,
    text_to_pic,
    capture_element,
    template_to_pic,
    template_to_html,
)

driver = nonebot.get_driver()
config = driver.config


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
    logger.info("Browser Stopped.")


browser_init = init

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
