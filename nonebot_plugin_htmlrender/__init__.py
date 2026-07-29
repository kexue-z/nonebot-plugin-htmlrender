from nonebot import require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")

from nonebot_plugin_htmlrender.api import (
    get_default_application as get_default_application,
)
from nonebot_plugin_htmlrender.api import (
    get_default_renderer as get_default_renderer,
)
from nonebot_plugin_htmlrender.api import prepare_html as prepare_html
from nonebot_plugin_htmlrender.api import prepare_markdown as prepare_markdown
from nonebot_plugin_htmlrender.api import prepare_template as prepare_template
from nonebot_plugin_htmlrender.api import prepare_text as prepare_text
from nonebot_plugin_htmlrender.api import (
    rasterize_html as rasterize_html,
)
from nonebot_plugin_htmlrender.api import (
    render_html as render_html,
)
from nonebot_plugin_htmlrender.api import (
    render_markdown as render_markdown,
)
from nonebot_plugin_htmlrender.api import (
    render_template as render_template,
)
from nonebot_plugin_htmlrender.api import (
    render_template_html as render_template_html,
)
from nonebot_plugin_htmlrender.api import (
    render_text as render_text,
)
from nonebot_plugin_htmlrender.api import (
    resolve_template_vars as resolve_template_vars,
)
from nonebot_plugin_htmlrender.api import (
    set_default_application as set_default_application,
)
from nonebot_plugin_htmlrender.api import to_resource_url as to_resource_url
from nonebot_plugin_htmlrender.application import (
    Application as Application,
)
from nonebot_plugin_htmlrender.application import (
    Renderer as Renderer,
)
from nonebot_plugin_htmlrender.bootstrap.plugin import initialize_plugin
from nonebot_plugin_htmlrender.bootstrap.settings import (
    RenderPluginConfig as RenderPluginConfig,
)
from nonebot_plugin_htmlrender.bootstrap.settings import (
    RenderSettings as RenderSettings,
)
from nonebot_plugin_htmlrender.preparation import (
    DocumentBase as DocumentBase,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset as PreparedAsset,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedHtml as PreparedHtml,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedStylesheet as PreparedStylesheet,
)
from nonebot_plugin_htmlrender.preparation import (
    RasterOptions as RasterOptions,
)
from nonebot_plugin_htmlrender.preparation import (
    RenderRequirement as RenderRequirement,
)
from nonebot_plugin_htmlrender.raster import (
    RasterImageFormat as RasterImageFormat,
)
from nonebot_plugin_htmlrender.rendering import (
    ApplicationNotInitialized as ApplicationNotInitialized,
)
from nonebot_plugin_htmlrender.rendering import (
    CapabilityCatalog as CapabilityCatalog,
)
from nonebot_plugin_htmlrender.rendering import (
    CapabilityKey as CapabilityKey,
)
from nonebot_plugin_htmlrender.rendering import (
    CapabilityUnavailable as CapabilityUnavailable,
)
from nonebot_plugin_htmlrender.rendering import ErrorCause as ErrorCause
from nonebot_plugin_htmlrender.rendering import (
    InvalidRenderRequest as InvalidRenderRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    PreparationError as PreparationError,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError as ProviderExecutionError,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderLifecycleError as ProviderLifecycleError,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderNotFound as ProviderNotFound,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderUnavailable as ProviderUnavailable,
)
from nonebot_plugin_htmlrender.rendering import (
    RasterizeHtmlRequest as RasterizeHtmlRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderedHtml as RenderedHtml,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderedImage as RenderedImage,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderHtmlRequest as RenderHtmlRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderingError as RenderingError,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderMarkdownRequest as RenderMarkdownRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderTemplateHtmlRequest as RenderTemplateHtmlRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderTemplateRequest as RenderTemplateRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    RenderTextRequest as RenderTextRequest,
)
from nonebot_plugin_htmlrender.rendering import (
    ResourcePolicy as ResourcePolicy,
)
from nonebot_plugin_htmlrender.rendering import (
    ResourceResolutionError as ResourceResolutionError,
)
from nonebot_plugin_htmlrender.rendering import (
    UnsupportedRenderOption as UnsupportedRenderOption,
)
from nonebot_plugin_htmlrender.rendering import (
    UnsupportedRequirement as UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.resources import (
    ResourceResolution as ResourceResolution,
)

__plugin_meta__: PluginMetadata = PluginMetadata(
    name="nonebot-plugin-htmlrender",
    description="提供可插拔 HTML 渲染与独立的类型化栅格场景能力",
    usage=(
        "提供 HTML/Markdown/模板渲染为图片的能力，作为库插件供其他插件调用。\n"
        "主要接口：render_html, render_text, render_markdown, render_template 等。"
    ),
    type="library",
    config=RenderPluginConfig,
    homepage="https://github.com/kexue-z/nonebot-plugin-htmlrender",
    supported_adapters=None,
)

initialize_plugin()

__all__ = [
    "Application",
    "ApplicationNotInitialized",
    "CapabilityCatalog",
    "CapabilityKey",
    "CapabilityUnavailable",
    "DocumentBase",
    "ErrorCause",
    "InvalidRenderRequest",
    "PreparationError",
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "ProviderExecutionError",
    "ProviderLifecycleError",
    "ProviderNotFound",
    "ProviderUnavailable",
    "RasterImageFormat",
    "RasterOptions",
    "RasterizeHtmlRequest",
    "RenderHtmlRequest",
    "RenderMarkdownRequest",
    "RenderPluginConfig",
    "RenderRequirement",
    "RenderSettings",
    "RenderTemplateHtmlRequest",
    "RenderTemplateRequest",
    "RenderTextRequest",
    "RenderedHtml",
    "RenderedImage",
    "Renderer",
    "RenderingError",
    "ResourcePolicy",
    "ResourceResolution",
    "ResourceResolutionError",
    "UnsupportedRenderOption",
    "UnsupportedRequirement",
    "get_default_application",
    "get_default_renderer",
    "prepare_html",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
    "rasterize_html",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
    "resolve_template_vars",
    "set_default_application",
    "to_resource_url",
]
