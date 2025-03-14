import nonebot
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from nonebot_plugin_htmlrender.browser import get_browser as get_browser
from nonebot_plugin_htmlrender.browser import get_new_page as get_new_page
from nonebot_plugin_htmlrender.browser import init_browser as init_browser
from nonebot_plugin_htmlrender.browser import shutdown_browser as shutdown_browser
from nonebot_plugin_htmlrender.browser import start_browser as start_browser
from nonebot_plugin_htmlrender.config import Config
from nonebot_plugin_htmlrender.data_source import capture_element as capture_element
from nonebot_plugin_htmlrender.data_source import html_to_pic as html_to_pic
from nonebot_plugin_htmlrender.data_source import md_to_pic as md_to_pic
from nonebot_plugin_htmlrender.data_source import template_to_html as template_to_html
from nonebot_plugin_htmlrender.data_source import template_to_pic as template_to_pic
from nonebot_plugin_htmlrender.data_source import text_to_pic as text_to_pic

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-htmlrender",
    description="通过浏览器渲染图片",
    usage="",
    type="library",
    config=Config,
    homepage="https://github.com/kexue-z/nonebot-plugin-htmlrender",
    extra={},
)

driver = nonebot.get_driver()


@driver.on_startup
async def init(**kwargs):
    logger.info("HTMLRender Starting...")
    await init_browser(**kwargs)
    logger.info("HTMLRender Started.")


@driver.on_shutdown
async def shutdown():
    logger.info("HTMLRender Shutting down...")
    await shutdown_browser()
    logger.info("HTMLRender Shut down.")


__all__ = [
    "capture_element",
    "get_new_page",
    "html_to_pic",
    "md_to_pic",
    "shutdown_browser",
    "start_browser",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
]
