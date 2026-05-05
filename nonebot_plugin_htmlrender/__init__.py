# ruff: noqa: I001
import nonebot
from nonebot import require

require("nonebot_plugin_localstore")
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from nonebot_plugin_htmlrender.render import (
    get_browser,
    get_browser_manager_registry,
    get_render_registry,
    get_render_endpoint,
    get_render_endpoint_registry,
    get_new_page,
    shutdown_all_browser_managers,
    shutdown_all_render_managers,
    shutdown_htmlrender,
    shutdown_render_endpoint,
    startup_htmlrender,
    startup_render,
    startup_render_endpoint,
)
from nonebot_plugin_htmlrender.config import Config, plugin_config
from nonebot_plugin_htmlrender.backend.playwright.data_source import (
    capture_element,
    html_to_pic,
    md_to_pic,
    template_to_html,
    template_to_pic,
    text_to_pic,
)
from nonebot_plugin_htmlrender.utils import clear_playwright_env_vars

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
    await startup_render(**kwargs)
    logger.opt(colors=True).info(
        f"HTMLRender Started with <cyan>{plugin_config.render_playwright.engine}</cyan>."
    )


@driver.on_shutdown
async def shutdown():
    logger.info("HTMLRender Shutting down...")
    await shutdown_all_render_managers()
    clear_playwright_env_vars()
    logger.info("HTMLRender Shut down.")


__all__ = [
    "capture_element",
    "get_browser",
    "get_browser_manager_registry",
    "get_new_page",
    "get_render_endpoint",
    "get_render_endpoint_registry",
    "get_render_registry",
    "html_to_pic",
    "md_to_pic",
    "shutdown_all_browser_managers",
    "shutdown_all_render_managers",
    "shutdown_htmlrender",
    "shutdown_render_endpoint",
    "startup_htmlrender",
    "startup_render",
    "startup_render_endpoint",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
]
