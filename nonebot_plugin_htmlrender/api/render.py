"""Engine-neutral convenience functions returning typed artifacts.

These are the stable top-level render commands. They accept only
cross-engine semantics; provider-specific knobs live in the typed
capability objects resolved from ``Application.extensions``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation.models import RasterOptions

# Keep the shared alias available to runtime annotation introspection.
from nonebot_plugin_htmlrender.raster import RasterImageFormat  # noqa: TC001
from nonebot_plugin_htmlrender.rendering.requests import (
    RasterizeHtmlRequest,
    RenderHtmlRequest,
    RenderMarkdownRequest,
    RenderTemplateHtmlRequest,
    RenderTemplateRequest,
    RenderTextRequest,
)

from ._default import get_default_renderer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.rendering.artifacts import (
        RenderedHtml,
        RenderedImage,
    )
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )


def _raster_options(
    *,
    width: int,
    height: int | None,
    device_pixel_ratio: float,
    image_format: RasterImageFormat,
    quality: int | None,
) -> RasterOptions:
    return RasterOptions(
        width=width,
        height=height,
        device_pixel_ratio=device_pixel_ratio,
        format=image_format,
        quality=quality,
    )


async def render_html(
    html: str,
    *,
    width: int = 800,
    height: int | None = None,
    device_pixel_ratio: float = 2.0,
    image_format: RasterImageFormat = "png",
    quality: int | None = None,
    base_url: str | None = None,
    resource_policy: ResourcePolicy | None = None,
    timeout_seconds: float | None = None,
) -> RenderedImage:
    """Render an HTML document into a raster image."""
    request = RenderHtmlRequest(
        html=html,
        raster=_raster_options(
            width=width,
            height=height,
            device_pixel_ratio=device_pixel_ratio,
            image_format=image_format,
            quality=quality,
        ),
        base_url=base_url,
        resource_policy=resource_policy,
        timeout_seconds=timeout_seconds,
    )
    return await get_default_renderer().render_html(request)


async def render_text(
    text: str,
    *,
    css_path: str = "",
    width: int = 500,
    height: int | None = None,
    device_pixel_ratio: float = 2.0,
    image_format: RasterImageFormat = "png",
    quality: int | None = None,
    resource_policy: ResourcePolicy | None = None,
    timeout_seconds: float | None = None,
) -> RenderedImage:
    """Render plain text into a raster image."""
    request = RenderTextRequest(
        text=text,
        css_path=css_path,
        raster=_raster_options(
            width=width,
            height=height,
            device_pixel_ratio=device_pixel_ratio,
            image_format=image_format,
            quality=quality,
        ),
        resource_policy=resource_policy,
        timeout_seconds=timeout_seconds,
    )
    return await get_default_renderer().render_text(request)


async def render_markdown(
    markdown: str = "",
    *,
    markdown_path: str = "",
    css_path: str = "",
    width: int = 500,
    height: int | None = None,
    device_pixel_ratio: float = 2.0,
    image_format: RasterImageFormat = "png",
    quality: int | None = None,
    resource_policy: ResourcePolicy | None = None,
    timeout_seconds: float | None = None,
) -> RenderedImage:
    """Render Markdown content into a raster image."""
    request = RenderMarkdownRequest(
        markdown=markdown,
        markdown_path=markdown_path,
        css_path=css_path,
        raster=_raster_options(
            width=width,
            height=height,
            device_pixel_ratio=device_pixel_ratio,
            image_format=image_format,
            quality=quality,
        ),
        resource_policy=resource_policy,
        timeout_seconds=timeout_seconds,
    )
    return await get_default_renderer().render_markdown(request)


async def render_template(
    template_path: str | Path,
    template_name: str,
    variables: Mapping[str, object] | None = None,
    *,
    filters: Mapping[str, FilterCallable] | None = None,
    extensions: Sequence[ExtensionSpec] = (),
    width: int = 500,
    height: int | None = None,
    device_pixel_ratio: float = 2.0,
    image_format: RasterImageFormat = "png",
    quality: int | None = None,
    resource_policy: ResourcePolicy | None = None,
    timeout_seconds: float | None = None,
) -> RenderedImage:
    """Render a Jinja template into a raster image."""
    request = RenderTemplateRequest(
        template_path=template_path,
        template_name=template_name,
        variables=dict(variables or {}),
        filters=filters,
        extensions=extensions,
        raster=_raster_options(
            width=width,
            height=height,
            device_pixel_ratio=device_pixel_ratio,
            image_format=image_format,
            quality=quality,
        ),
        resource_policy=resource_policy,
        timeout_seconds=timeout_seconds,
    )
    return await get_default_renderer().render_template(request)


async def render_template_html(
    template_path: str | Path,
    template_name: str,
    variables: Mapping[str, object] | None = None,
    *,
    filters: Mapping[str, FilterCallable] | None = None,
    extensions: Sequence[ExtensionSpec] = (),
) -> RenderedHtml:
    """Render a Jinja template into an HTML string artifact."""
    request = RenderTemplateHtmlRequest(
        template_path=template_path,
        template_name=template_name,
        variables=dict(variables or {}),
        filters=filters,
        extensions=extensions,
    )
    return await get_default_renderer().render_template_html(request)


async def rasterize_html(
    prepared: PreparedHtml,
    options: RasterOptions | None = None,
    *,
    resource_policy: ResourcePolicy | None = None,
    timeout_seconds: float | None = None,
) -> RenderedImage:
    """Execute an already prepared HTML document into a raster image."""
    request = RasterizeHtmlRequest(
        prepared=prepared,
        options=options if options is not None else RasterOptions(),
        resource_policy=resource_policy,
        timeout_seconds=timeout_seconds,
    )
    return await get_default_renderer().rasterize_html(request)


__all__ = [
    "rasterize_html",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
]
