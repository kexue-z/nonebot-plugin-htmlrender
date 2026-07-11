"""Renderer use cases wired by constructor injection.

Each use case owns exactly one public render command: it prepares neutral
content into the shared ``PreparedHtml`` IR and hands execution to the
injected ``PreparedHtmlExecutor``. Use cases never touch providers,
registries, or process-global configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.rendering.artifacts import RenderedHtml, RenderedImage
from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.models import RasterOptions
    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.rendering.ports import PreparedHtmlExecutor
    from nonebot_plugin_htmlrender.rendering.requests import (
        RasterizeHtmlRequest,
        RenderHtmlRequest,
        RenderMarkdownRequest,
        RenderTemplateHtmlRequest,
        RenderTemplateRequest,
        RenderTextRequest,
    )


def _rendered_image(options: RasterOptions, data: bytes) -> RenderedImage:
    return RenderedImage(
        data=data,
        format=options.format,
        width=options.width,
        height=options.height,
    )


def _preparation_strictness(policy: ResourcePolicy | None) -> bool | None:
    """Map the per-call resource policy onto preparation-time strictness.

    ``None`` and ``OFF`` skip preparation-time materialization; the executor
    still receives the policy and applies its own transport rules.
    """
    if policy is ResourcePolicy.STRICT:
        return True
    if policy is ResourcePolicy.AUTO:
        return False
    return None


@final
class RenderHtml:
    def __init__(
        self,
        *,
        preparer: HtmlPreparer,
        executor: PreparedHtmlExecutor,
    ) -> None:
        self._preparer = preparer
        self._executor = executor

    async def execute(self, request: RenderHtmlRequest) -> RenderedImage:
        prepared = await self._preparer.prepare_html(
            request.html,
            base_url=request.base_url,
        )
        data = await self._executor.execute(
            prepared,
            request.raster,
            resource_policy=request.resource_policy,
            timeout_seconds=request.timeout_seconds,
        )
        return _rendered_image(request.raster, data)


@final
class RenderText:
    def __init__(
        self,
        *,
        preparer: HtmlPreparer,
        executor: PreparedHtmlExecutor,
    ) -> None:
        self._preparer = preparer
        self._executor = executor

    async def execute(self, request: RenderTextRequest) -> RenderedImage:
        prepared = await self._preparer.prepare_text(
            request.text,
            css_path=request.css_path,
        )
        data = await self._executor.execute(
            prepared,
            request.raster,
            timeout_seconds=request.timeout_seconds,
        )
        return _rendered_image(request.raster, data)


@final
class RenderMarkdown:
    def __init__(
        self,
        *,
        preparer: HtmlPreparer,
        executor: PreparedHtmlExecutor,
    ) -> None:
        self._preparer = preparer
        self._executor = executor

    async def execute(self, request: RenderMarkdownRequest) -> RenderedImage:
        prepared = await self._preparer.prepare_markdown(
            request.markdown,
            markdown_path=request.markdown_path,
            css_path=request.css_path,
            resource_strict=_preparation_strictness(request.resource_policy),
        )
        data = await self._executor.execute(
            prepared,
            request.raster,
            resource_policy=request.resource_policy,
            timeout_seconds=request.timeout_seconds,
        )
        return _rendered_image(request.raster, data)


@final
class RenderTemplate:
    def __init__(
        self,
        *,
        preparer: HtmlPreparer,
        executor: PreparedHtmlExecutor,
    ) -> None:
        self._preparer = preparer
        self._executor = executor

    async def execute(self, request: RenderTemplateRequest) -> RenderedImage:
        prepared = await self._preparer.prepare_template(
            request.template_path,
            request.template_name,
            request.variables,
            filters=request.filters,
            extensions=request.extensions,
        )
        data = await self._executor.execute(
            prepared,
            request.raster,
            resource_policy=request.resource_policy,
            timeout_seconds=request.timeout_seconds,
        )
        return _rendered_image(request.raster, data)


@final
class RenderTemplateHtml:
    def __init__(self, *, preparer: HtmlPreparer) -> None:
        self._preparer = preparer

    async def execute(self, request: RenderTemplateHtmlRequest) -> RenderedHtml:
        content = await self._preparer.render_template_html(
            request.template_path,
            request.template_name,
            request.variables,
            filters=request.filters,
            extensions=request.extensions,
        )
        return RenderedHtml(content=content)


@final
class RasterizeHtml:
    def __init__(self, *, executor: PreparedHtmlExecutor) -> None:
        self._executor = executor

    async def execute(self, request: RasterizeHtmlRequest) -> RenderedImage:
        data = await self._executor.execute(
            request.prepared,
            request.options,
            resource_policy=request.resource_policy,
            timeout_seconds=request.timeout_seconds,
        )
        return _rendered_image(request.options, data)
