import nonebot
from nonebot import require

require("nonebot_plugin_localstore")
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from nonebot_plugin_htmlrender.browser import (
    get_new_page,
    shutdown_htmlrender,
    startup_htmlrender,
)
from nonebot_plugin_htmlrender.config import Config, plugin_config
from nonebot_plugin_htmlrender.data_source import (
    capture_element,
    html_to_pic,
    md_to_pic,
    template_to_html,
    template_to_pic,
    text_to_pic,
)
from nonebot_plugin_htmlrender.utils import _clear_playwright_env_vars

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
    await startup_htmlrender(**kwargs)
    logger.opt(colors=True).info(
        f"HTMLRender Started with <cyan>{plugin_config.htmlrender_browser}</cyan>."
    )


@driver.on_shutdown
async def shutdown():
    logger.info("HTMLRender Shutting down...")
    await shutdown_htmlrender()
    _clear_playwright_env_vars()
    logger.info("HTMLRender Shut down.")


__all__ = [
    "capture_element",
    "get_new_page",
    "html_to_pic",
    "md_to_pic",
    "shutdown_htmlrender",
    "startup_htmlrender",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
]
