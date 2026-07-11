"""Assembly of the application object graph from composed engine bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer

from .app import Application
from .bindings import RendererBindings
from .renderer import Renderer
from .use_cases import (
    RasterizeHtml,
    RenderHtml,
    RenderMarkdown,
    RenderTemplate,
    RenderTemplateHtml,
    RenderText,
)

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.providers.sdk import EngineBindings
    from nonebot_plugin_htmlrender.rendering.ports import PreparedHtmlExecutor


def build_renderer_bindings(
    *,
    executor: PreparedHtmlExecutor | None,
    preparer: HtmlPreparer,
) -> RendererBindings:
    """Derive use-case bindings from what the engine actually provides.

    Without an executor only the html-producing use case is available;
    renderer capabilities follow from the bindings, never from declarations.
    """
    template_html = RenderTemplateHtml(preparer=preparer)
    if executor is None:
        return RendererBindings(render_template_html=template_html)
    return RendererBindings(
        render_html=RenderHtml(preparer=preparer, executor=executor),
        render_text=RenderText(preparer=preparer, executor=executor),
        render_markdown=RenderMarkdown(preparer=preparer, executor=executor),
        render_template=RenderTemplate(preparer=preparer, executor=executor),
        render_template_html=template_html,
        rasterize_html=RasterizeHtml(executor=executor),
    )


def build_application(
    *,
    engine: EngineBindings,
    preparer: HtmlPreparer | None = None,
) -> Application:
    """Assemble an Application around one composed engine."""
    resolved_preparer = preparer if preparer is not None else DefaultHtmlPreparer()
    bindings = build_renderer_bindings(
        executor=engine.prepared_html_executor,
        preparer=resolved_preparer,
    )
    return Application(
        renderer=Renderer(bindings),
        lifecycle=engine.lifecycle,
        capabilities=engine.provider_capabilities,
    )


__all__ = ["build_application", "build_renderer_bindings"]
