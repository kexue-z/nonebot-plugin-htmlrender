from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import TYPE_CHECKING, Any, Literal, cast

from nonebot_plugin_htmlrender.backend.playwright.models import (
    HtmlRenderRequest,
    TemplateConfig,
    TemplateRenderRequest,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedHtml,
    RasterOptions,
    prepare_html,
    prepare_markdown,
    prepare_template,
    prepare_text,
)
from nonebot_plugin_htmlrender.resources.templating import (
    render_template_html as render_jinja_template_html,
)

from .errors import TakumiUnsupportedError
from .runtime import TakumiRuntimeState, render_defaults
from .source import materialize_takumi_document

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.backend.playwright.models import (
        RenderConfig,
    )
    from nonebot_plugin_htmlrender.resources.templating import FilterCallable

    from .types import StaticImageFormat, TakumiImageInput


def device_dimension(value: int | None, device_pixel_ratio: float) -> int | None:
    """Map a CSS-pixel dimension to Takumi's device-pixel canvas dimension."""
    if value is None:
        return None
    if value <= 0:
        raise ValueError("render dimensions must be greater than zero")
    return math.ceil(value * device_pixel_ratio)


def validate_device_pixel_ratio(value: float) -> float:
    ratio = float(value)
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError(
            "device_scale_factor must be a finite number greater than zero"
        )
    return ratio


def _viewport_dimensions(
    viewport: object,
    *,
    default_width: int,
    default_height: int,
) -> tuple[int, int]:
    if viewport is None:
        return default_width, default_height
    if isinstance(viewport, Mapping):
        width = viewport.get("width", default_width)
        height = viewport.get("height", default_height)
    else:
        width = getattr(viewport, "width", default_width)
        height = getattr(viewport, "height", default_height)
    if not isinstance(width, int) or isinstance(width, bool):
        raise TypeError("viewport width must be an integer")
    if not isinstance(height, int) or isinstance(height, bool):
        raise TypeError("viewport height must be an integer")
    return width, height


def _reject_wait(wait_ms: int) -> None:
    if wait_ms:
        raise TakumiUnsupportedError(
            "Takumi renders synchronously and cannot wait for scripts, network, or DOM "
            "updates; wait values must be zero."
        )


def _reject_browser_page_options(options: Mapping[str, object]) -> None:
    metadata_only = {"base_url", "template_path", "screenshot_timeout"}
    unsupported = sorted(
        key
        for key, value in options.items()
        if key not in metadata_only and value is not None
    )
    if unsupported:
        names = ", ".join(unsupported)
        raise TakumiUnsupportedError(
            f"Takumi has no browser page context; unsupported options: {names}."
        )


def _render_config_spec(
    render: RenderConfig,
) -> tuple[int, int | None, float, StaticImageFormat, int | None]:
    page = render.page
    screenshot = render.screenshot
    _reject_wait(screenshot.wait_before_screenshot)
    if page.user_agent is not None or page.extra_http_headers:
        raise TakumiUnsupportedError(
            "Takumi performs no HTTP requests and cannot apply user_agent or "
            "extra_http_headers."
        )
    if page.document_url is not None:
        raise TakumiUnsupportedError(
            "Takumi has no browser navigation and cannot apply document_url. "
            "Prepare resource bases through PreparedHtml.base_url instead."
        )

    height = None if screenshot.full_page else page.viewport.height
    quality = cast("int | None", getattr(screenshot, "quality", None))
    return (
        page.viewport.width,
        height,
        screenshot.device_scale_factor,
        cast("StaticImageFormat", screenshot.format),
        quality,
    )


async def render_prepared_html(
    state: TakumiRuntimeState,
    prepared: PreparedHtml,
    *,
    stylesheets: Sequence[str] = (),
    images: Sequence[TakumiImageInput | object] | None = None,
    width: int | None = 800,
    height: int | None = None,
    image_format: StaticImageFormat = "png",
    quality: int | None = None,
    device_pixel_ratio: float = 1.0,
    lossless: bool | None = None,
    font_size: float = 16.0,
    draw_debug_border: bool = False,
    time_ms: int = 0,
    dithering: Literal["none", "ordered-bayer", "floyd-steinberg"] = "none",
    lang: str | None = None,
    font_families: Sequence[str] | None = None,
    keyframes: object | None = None,
) -> bytes:
    """Execute a backend-neutral prepared document with Takumi."""
    ratio = validate_device_pixel_ratio(device_pixel_ratio)
    document = await materialize_takumi_document(
        prepared,
        stylesheets=stylesheets,
        images=images,
    )
    native_options = render_defaults(state, images=document.images)
    native_options.update(
        width=device_dimension(width, ratio),
        height=device_dimension(height, ratio),
        format=image_format,
        font_size=font_size,
        device_pixel_ratio=ratio,
        draw_debug_border=draw_debug_border,
        time_ms=time_ms,
        dithering=dithering,
    )
    if quality is not None:
        native_options["quality"] = quality
    if lossless is not None:
        native_options["lossless"] = lossless
    if lang is not None:
        native_options["lang"] = lang
    if font_families is not None:
        native_options["font_families"] = tuple(font_families)
    if keyframes is not None:
        native_options["keyframes"] = keyframes

    rendered = await state.call_document(
        "render_compiled",
        document.html,
        document.stylesheets,
        **native_options,
    )
    if not isinstance(rendered, bytes):
        raise TypeError(f"Takumi returned {type(rendered).__name__}, expected bytes.")
    return rendered


async def rasterize_html(
    state: TakumiRuntimeState,
    prepared: PreparedHtml,
    options: RasterOptions,
) -> bytes:
    return await render_prepared_html(
        state,
        prepared,
        width=options.width,
        height=options.height,
        image_format=options.format,
        quality=options.quality,
        device_pixel_ratio=options.device_pixel_ratio,
    )


async def render_html(
    state: TakumiRuntimeState,
    request: HtmlRenderRequest | str,
    *,
    wait: int = 0,
    template_path: str | None = None,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2.0,
    screenshot_timeout: float | None = 30_000,
    full_page: bool = True,
    **page_options: object,
) -> bytes:
    if isinstance(request, HtmlRenderRequest):
        _reject_wait(request.content.additional_wait)
        width, height, ratio, image_format, request_quality = _render_config_spec(
            request.render
        )
        prepared = prepare_html(request.content.html)
        return await render_prepared_html(
            state,
            prepared,
            width=width,
            height=height,
            image_format=image_format,
            quality=request_quality,
            device_pixel_ratio=ratio,
        )

    _reject_wait(wait)
    viewport = page_options.pop("viewport", None)
    width, viewport_height = _viewport_dimensions(
        viewport,
        default_width=800,
        default_height=600,
    )
    _reject_browser_page_options(
        {
            **page_options,
            "template_path": template_path,
            "screenshot_timeout": screenshot_timeout,
        }
    )
    prepared = prepare_html(request, base_url=template_path)
    return await render_prepared_html(
        state,
        prepared,
        width=width,
        height=None if full_page else viewport_height,
        image_format=image_type,
        quality=quality,
        device_pixel_ratio=device_scale_factor,
    )


def _spec_from_optional_render(
    render: RenderConfig | None,
    *,
    width: int,
    image_type: Literal["jpeg", "png"],
    quality: int | None,
    device_scale_factor: float,
) -> tuple[int, int | None, float, StaticImageFormat, int | None]:
    if render is not None:
        return _render_config_spec(render)
    return width, None, device_scale_factor, image_type, quality


async def render_text(
    state: TakumiRuntimeState,
    text: str,
    *,
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2.0,
    screenshot_timeout: float | None = 30_000,
    render: RenderConfig | None = None,
) -> bytes:
    del screenshot_timeout
    prepared = await prepare_text(text, css_path=css_path)
    render_width, render_height, ratio, image_format, render_quality = (
        _spec_from_optional_render(
            render,
            width=width,
            image_type=image_type,
            quality=quality,
            device_scale_factor=device_scale_factor,
        )
    )
    return await render_prepared_html(
        state,
        prepared,
        width=render_width,
        height=render_height,
        image_format=image_format,
        quality=render_quality,
        device_pixel_ratio=ratio,
    )


async def render_markdown(
    state: TakumiRuntimeState,
    markdown_text: str = "",
    *,
    md: str = "",
    md_path: str = "",
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2.0,
    screenshot_timeout: float | None = 30_000,
    resource_strict: bool = True,
    render: RenderConfig | None = None,
) -> bytes:
    del screenshot_timeout
    source = md or markdown_text
    prepared = await prepare_markdown(
        source,
        markdown_path=md_path,
        css_path=css_path,
        resource_strict=resource_strict,
    )
    render_width, render_height, ratio, image_format, render_quality = (
        _spec_from_optional_render(
            render,
            width=width,
            image_type=image_type,
            quality=quality,
            device_scale_factor=device_scale_factor,
        )
    )
    return await render_prepared_html(
        state,
        prepared,
        width=render_width,
        height=render_height,
        image_format=image_format,
        quality=render_quality,
        device_pixel_ratio=ratio,
    )


async def _prepare_template_config(
    template: TemplateConfig | str,
    *,
    template_name: str | None,
    filters: Mapping[str, Any] | None,
    variables: Mapping[str, object],
) -> PreparedHtml:
    if isinstance(template, TemplateConfig):
        template_path = template.template_path
        resolved_name = template.template_name
        resolved_filters = template.custom_filters or filters
        resolved_variables = {**template.template_vars, **variables}
    else:
        if template_name is None:
            raise ValueError("template_name is required when template is a path string")
        template_path = template
        resolved_name = template_name
        resolved_filters = filters
        resolved_variables = dict(variables)

    return await prepare_template(
        template_path,
        resolved_name,
        resolved_variables,
        filters=cast("Mapping[str, FilterCallable] | None", resolved_filters),
    )


async def render_template_html(
    template: TemplateConfig | str,
    *,
    template_name: str | None = None,
    filters: Mapping[str, Any] | None = None,
    **variables: object,
) -> str:
    if isinstance(template, TemplateConfig):
        template_path = template.template_path
        resolved_name = template.template_name
        resolved_filters = template.custom_filters or filters
        resolved_variables = {**template.template_vars, **variables}
    else:
        if template_name is None:
            raise ValueError("template_name is required when template is a path string")
        template_path = template
        resolved_name = template_name
        resolved_filters = filters
        resolved_variables = variables

    return await render_jinja_template_html(
        template_path,
        resolved_name,
        resolved_variables,
        filters=cast("Mapping[str, FilterCallable] | None", resolved_filters),
    )


async def render_template(
    state: TakumiRuntimeState,
    request: TemplateRenderRequest | str,
    *,
    template_name: str | None = None,
    templates: dict[str, Any] | None = None,
    filters: Mapping[str, Any] | None = None,
    pages: Mapping[str, object] | None = None,
    wait: int = 0,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2.0,
    screenshot_timeout: float | None = 30_000,
    resolve_resources: bool | None = None,
    resource_resolver: object | None = None,
    resource_strict: bool = False,
) -> bytes:
    del screenshot_timeout, resource_strict
    _reject_wait(wait)
    if resolve_resources or resource_resolver is not None:
        raise TakumiUnsupportedError(
            "The Playwright URL/filehost resource resolver cannot feed Takumi. "
            "Use TakumiExtension with explicit image bytes instead."
        )

    if isinstance(request, TemplateRenderRequest):
        prepared = await _prepare_template_config(
            request.template,
            template_name=None,
            filters=None,
            variables={},
        )
        width, height, ratio, image_format, render_quality = _render_config_spec(
            request.render
        )
    else:
        prepared = await _prepare_template_config(
            request,
            template_name=template_name,
            filters=filters,
            variables=templates or {},
        )
        page_options = dict(pages or {})
        viewport = page_options.pop("viewport", None)
        width, _ = _viewport_dimensions(
            viewport,
            default_width=500,
            default_height=10,
        )
        _reject_browser_page_options(page_options)
        height = None
        ratio = device_scale_factor
        image_format = image_type
        render_quality = quality

    return await render_prepared_html(
        state,
        prepared,
        width=width,
        height=height,
        image_format=image_format,
        quality=render_quality,
        device_pixel_ratio=ratio,
    )


__all__ = [
    "device_dimension",
    "rasterize_html",
    "render_html",
    "render_markdown",
    "render_prepared_html",
    "render_template",
    "render_template_html",
    "render_text",
    "validate_device_pixel_ratio",
]
