import nonebot
from nonebot.log import logger
from nonebot.plugin import export

from .browser import get_browser, shutdown_browser


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


export.browser = init


@driver.on_shutdown
async def shutdown():
    await shutdown_browser()
    logger.info("Browser Stoped.")


