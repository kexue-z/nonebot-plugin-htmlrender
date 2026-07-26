"""Renderer use cases wired by constructor injection.

Each use case owns exactly one public render command: it prepares neutral
content into the shared ``PreparedHtml`` IR and hands execution to the
injected ``PreparedHtmlExecutor``. Use cases never touch providers,
registries, or process-global configuration.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, final

import anyio

from nonebot_plugin_htmlrender.rendering.artifacts import RenderedHtml, RenderedImage
from nonebot_plugin_htmlrender.rendering.errors import ProviderExecutionError
from nonebot_plugin_htmlrender.rendering.requests import resolve_mode_for_policy

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.rendering.ports import PreparedHtmlExecutor
    from nonebot_plugin_htmlrender.rendering.requests import (
        RasterizeHtmlRequest,
        RenderHtmlRequest,
        RenderMarkdownRequest,
        RenderTemplateHtmlRequest,
        RenderTemplateRequest,
        RenderTextRequest,
        ResourcePolicy,
    )
    from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode


def _preparation_resolve_mode(
    policy: ResourcePolicy | None,
) -> ResourceResolveMode | None:
    if policy is None:
        return None
    return resolve_mode_for_policy(policy)


@contextmanager
def _operation_timeout(timeout_seconds: float | None) -> Iterator[None]:
    if timeout_seconds is None:
        yield
        return
    try:
        with anyio.fail_after(timeout_seconds):
            yield
    except TimeoutError as error:
        raise ProviderExecutionError(
            f"Render operation timed out after {timeout_seconds} seconds.",
            source=error,
        ) from error


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
        with _operation_timeout(request.timeout_seconds):
            prepared = await self._preparer.prepare_html(
                request.html,
                base_url=request.base_url,
            )
            return await self._executor.execute(
                prepared,
                request.raster,
                resource_policy=request.resource_policy,
                timeout_seconds=request.timeout_seconds,
            )


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
        with _operation_timeout(request.timeout_seconds):
            prepared = await self._preparer.prepare_text(
                request.text,
                css_path=request.css_path,
            )
            return await self._executor.execute(
                prepared,
                request.raster,
                resource_policy=request.resource_policy,
                timeout_seconds=request.timeout_seconds,
            )


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
        with _operation_timeout(request.timeout_seconds):
            prepared = await self._preparer.prepare_markdown(
                request.markdown,
                markdown_path=request.markdown_path,
                css_path=request.css_path,
                resource_mode=_preparation_resolve_mode(request.resource_policy),
            )
            return await self._executor.execute(
                prepared,
                request.raster,
                resource_policy=request.resource_policy,
                timeout_seconds=request.timeout_seconds,
            )


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
        with _operation_timeout(request.timeout_seconds):
            prepared = await self._preparer.prepare_template(
                request.template_path,
                request.template_name,
                request.variables,
                filters=request.filters,
                extensions=request.extensions,
                resource_mode=_preparation_resolve_mode(request.resource_policy),
            )
            return await self._executor.execute(
                prepared,
                request.raster,
                resource_policy=request.resource_policy,
                timeout_seconds=request.timeout_seconds,
            )


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
        with _operation_timeout(request.timeout_seconds):
            return await self._executor.execute(
                request.prepared,
                request.options,
                resource_policy=request.resource_policy,
                timeout_seconds=request.timeout_seconds,
            )
