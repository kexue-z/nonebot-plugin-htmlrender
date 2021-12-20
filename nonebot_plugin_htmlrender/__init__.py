import nonebot
from nonebot.log import logger
from nonebot.plugin import export

from .browser import get_browser, shutdown_browser
from .date_source import text_to_pic

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


export.browser = init
export.text_to_pic = text_to_pic
