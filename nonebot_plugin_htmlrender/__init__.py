from importlib import import_module
from typing import Any

import nonebot
from nonebot import require
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")

from nonebot_plugin_htmlrender._bootstrap import (
    _bootstrap_filehost_guard_on_import as _bootstrap_filehost_guard_on_import,
)
from nonebot_plugin_htmlrender._bootstrap import (
    _bootstrap_optional_plugins_on_import as _bootstrap_optional_plugins_on_import,
)
from nonebot_plugin_htmlrender._bootstrap import (
    _patch_filehost_request_headers_validator as _patch_filehost_request_headers_validator,
)

_bootstrap_optional_plugins_on_import()
_bootstrap_filehost_guard_on_import()

from nonebot_plugin_htmlrender._compat import (
    capture_element as capture_element,
)
from nonebot_plugin_htmlrender._compat import (
    get_new_page as get_new_page,
)
from nonebot_plugin_htmlrender._compat import (
    html_to_pic as html_to_pic,
)
from nonebot_plugin_htmlrender._compat import (
    md_to_pic as md_to_pic,
)
from nonebot_plugin_htmlrender._compat import (
    shutdown_htmlrender as shutdown_htmlrender,
)
from nonebot_plugin_htmlrender._compat import (
    startup_htmlrender as startup_htmlrender,
)
from nonebot_plugin_htmlrender._compat import (
    template_to_html as template_to_html,
)
from nonebot_plugin_htmlrender._compat import (
    template_to_pic as template_to_pic,
)
from nonebot_plugin_htmlrender._compat import (
    text_to_pic as text_to_pic,
)
from nonebot_plugin_htmlrender.backend.base import BackendExtension
from nonebot_plugin_htmlrender.backend.factory import ensure_backend_loaded
from nonebot_plugin_htmlrender.config import Config, plugin_config
from nonebot_plugin_htmlrender.consts import RenderBackend, RenderStartupMode
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    PreparedHtml,
    PreparedStylesheet,
    RasterOptions,
    RenderRequirement,
    prepare_html,
    prepare_markdown,
    prepare_template,
    prepare_text,
)
from nonebot_plugin_htmlrender.render import (
    available_render_backends,
    capture_html_element,
    get_default_render,
    get_render,
    get_render_backend_status,
    get_render_context,
    is_render_backend_available,
    is_render_backend_registered,
    list_render_backend_statuses,
    probe_render,
    rasterize_html,
    registered_render_backends,
    render_html,
    render_markdown,
    render_template,
    render_template_html,
    render_text,
    require_render_extension,
    shutdown_render,
    startup_render,
    unavailable_render_backends,
)
from nonebot_plugin_htmlrender.resources import (
    ResourceResolveError,
    resolve_template_vars,
    to_resource_url,
)

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-htmlrender",
    description="使用 Playwright 或 Takumi 渲染 HTML、Markdown 与模板图片",
    usage=(
        "提供 HTML/Markdown/模板渲染为图片的能力，作为库插件供其他插件调用。\n"
        "主要接口：render_html, render_text, render_markdown, render_template 等。"
    ),
    type="library",
    config=Config,
    homepage="https://github.com/kexue-z/nonebot-plugin-htmlrender",
    supported_adapters=None,
)

driver = nonebot.get_driver()


def _prepare_playwright_startup() -> None:
    ensure_backend_loaded(RenderBackend.PLAYWRIGHT)
    page_module = import_module("nonebot_plugin_htmlrender.backend.playwright._page")
    register_render_context_provider = page_module.register_render_context_provider
    register_render_context_provider(get_render_context)


@driver.on_startup
async def init(**kwargs: Any) -> None:
    """插件启动时初始化渲染后端。"""
    logger.info("HTMLRender Starting...")
    if plugin_config.render_backend is None:
        logger.info("No render backend selected; startup skipped.")
        return

    try:
        startup_mode = plugin_config.render_startup_mode
        if startup_mode == RenderStartupMode.OFF:
            logger.info("Render startup skipped by configuration.")
            return
        if plugin_config.render_backend == RenderBackend.PLAYWRIGHT:
            filehost_module = import_module(
                "nonebot_plugin_htmlrender.resources.filehost"
            )
            ensure_filehost_runtime_ready = (
                filehost_module.ensure_filehost_runtime_ready
            )

            _prepare_playwright_startup()
            await ensure_filehost_runtime_ready(reason="plugin_startup")
        if startup_mode == RenderStartupMode.WARMUP:
            await startup_render(**kwargs)
        else:
            await startup_render(**kwargs)
            await probe_render()
    except Exception as e:
        logger.exception("Failed to start render runtime.")
        raise RuntimeError("Render runtime startup failed.") from e

    logger.opt(colors=True).info(
        f"HTMLRender Started with backend <cyan>{plugin_config.render_backend}</cyan>."
    )


@driver.on_shutdown
async def shutdown() -> None:
    """插件关闭时清理渲染资源。"""
    logger.info("HTMLRender Shutting down...")
    await shutdown_render()
    if plugin_config.render_backend == RenderBackend.PLAYWRIGHT:
        runtime_module = import_module(
            "nonebot_plugin_htmlrender.backend.playwright.runtime"
        )
        clear_playwright_env_vars = runtime_module.clear_playwright_env_vars

        clear_playwright_env_vars()
    logger.info("HTMLRender Shut down.")


__all__ = [
    "BackendExtension",
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "RasterOptions",
    "RenderRequirement",
    "ResourceResolveError",
    "available_render_backends",
    "capture_element",
    "capture_html_element",
    "get_default_render",
    "get_new_page",
    "get_render",
    "get_render_backend_status",
    "get_render_context",
    "html_to_pic",
    "is_render_backend_available",
    "is_render_backend_registered",
    "list_render_backend_statuses",
    "md_to_pic",
    "prepare_html",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
    "probe_render",
    "rasterize_html",
    "registered_render_backends",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
    "require_render_extension",
    "resolve_template_vars",
    "shutdown_htmlrender",
    "shutdown_render",
    "startup_htmlrender",
    "startup_render",
    "template_to_html",
    "template_to_pic",
    "text_to_pic",
    "to_resource_url",
    "unavailable_render_backends",
]
