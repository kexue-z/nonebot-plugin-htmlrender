from __future__ import annotations

# Keep Takumi's public ``format=`` spelling in the typed extension API.
# ruff: noqa: A002
from dataclasses import dataclass
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Literal,
    ParamSpec,
    TypeAlias,
    TypeVar,
    cast,
)

from nonebot_plugin_htmlrender.adapters._backend import BackendExtension
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.preparation import (
    PreparedHtml,
    prepare_html,
    prepare_template,
)
from nonebot_plugin_htmlrender.resources import (
    FileCachePolicy,
)
from nonebot_plugin_htmlrender.utils import track_render

from .operations import (
    device_dimension,
    render_prepared_html,
    validate_device_pixel_ratio,
)
from .runtime import TakumiRuntimeState, render_defaults
from .source import materialize_takumi_document
from .types import AnimationImageFormat, StaticImageFormat, TakumiImageResource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from takumi_py import (
        AnimationScene,
        CompiledNode,
        CompiledStyleSheet,
        DitheringAlgorithm,
        FontResourceInput,
        ImageResourceInput,
        KeyframesInput,
        MeasuredNode,
        NodeInput,
        RawAnimationFrame,
    )

    from nonebot_plugin_htmlrender.resources.templating import FilterCallable
    from nonebot_plugin_htmlrender.resources.weighted_cache import WeightedCacheStats

    ImageInput: TypeAlias = ImageResourceInput | TakumiImageResource
else:
    ImageInput: TypeAlias = object


P = ParamSpec("P")
R = TypeVar("R")


def _tracked(
    operation: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def _decorate(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def _wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            extension = cast("TakumiExtension", args[0])
            async with track_render(operation, backend=RenderBackend.TAKUMI):
                extension._state._ensure_open()
                return await func(*args, **kwargs)

        return _wrapped

    return _decorate


@dataclass(frozen=True, slots=True)
class TakumiCompiledDocument:
    """A compiled document tied to the renderer owned by one Takumi runtime."""

    node: CompiledNode
    stylesheets: tuple[CompiledStyleSheet, ...]
    images: tuple[object, ...] = ()


def _raster_kwargs(
    state: TakumiRuntimeState,
    *,
    width: int | None,
    height: int | None,
    format: StaticImageFormat,
    quality: int | None,
    lossless: bool | None,
    font_size: float,
    device_pixel_ratio: float,
    draw_debug_border: bool,
    time_ms: int,
    dithering: DitheringAlgorithm,
    images: Sequence[ImageInput] | None,
    keyframes: KeyframesInput | None,
    font_families: Sequence[str] | None,
    lang: str | None,
) -> dict[str, object]:
    ratio = validate_device_pixel_ratio(device_pixel_ratio)
    options = render_defaults(state, images=cast("Sequence[object] | None", images))
    options.update(
        width=device_dimension(width, ratio),
        height=device_dimension(height, ratio),
        format=format,
        font_size=font_size,
        device_pixel_ratio=ratio,
        draw_debug_border=draw_debug_border,
        time_ms=time_ms,
        dithering=dithering,
    )
    if quality is not None:
        options["quality"] = quality
    if lossless is not None:
        options["lossless"] = lossless
    if keyframes is not None:
        options["keyframes"] = keyframes
    if font_families is not None:
        options["font_families"] = tuple(font_families)
    if lang is not None:
        options["lang"] = lang
    return options


def _svg_kwargs(
    state: TakumiRuntimeState,
    *,
    width: int | None,
    height: int | None,
    font_size: float,
    time_ms: int,
    images: Sequence[ImageInput] | None,
    keyframes: KeyframesInput | None,
    font_families: Sequence[str] | None,
    lang: str | None,
) -> dict[str, object]:
    options = render_defaults(state, images=cast("Sequence[object] | None", images))
    options.update(
        width=width,
        height=height,
        font_size=font_size,
        time_ms=time_ms,
    )
    if keyframes is not None:
        options["keyframes"] = keyframes
    if font_families is not None:
        options["font_families"] = tuple(font_families)
    if lang is not None:
        options["lang"] = lang
    return options


def _expect_bytes(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(f"Takumi returned {type(value).__name__}, expected bytes.")
    return value


def _expect_svg(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Takumi returned {type(value).__name__}, expected str.")
    return value


@dataclass(frozen=True, slots=True)
class TakumiExtension:
    """Strongly typed access to Takumi-specific rendering capabilities.

    Raster dimensions use CSS pixels. They are converted to Takumi's device-pixel
    canvas so ``width=100, device_pixel_ratio=2`` produces a 200-pixel-wide image.
    Every synchronous native operation runs in the runtime's bounded worker pool.
    """

    _state: TakumiRuntimeState

    @property
    def registered_font_families(self) -> tuple[str, ...]:
        return self._state.registered_font_families

    @property
    def compiled_cache_stats(self) -> WeightedCacheStats:
        """Return an immutable snapshot of this runtime's compiled cache."""

        return self._state.compiled_cache_stats

    @_tracked("takumi.extension.compile_html")
    async def compile_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
    ) -> TakumiCompiledDocument:
        prepared = (
            html
            if isinstance(html, PreparedHtml)
            else prepare_html(html, base_url=base_url)
        )
        document = await materialize_takumi_document(
            prepared,
            stylesheets=stylesheets,
            images=cast("Sequence[object] | None", images),
        )
        node, compiled_stylesheets = await self._state.compile_document(
            document.html,
            document.stylesheets,
        )
        return TakumiCompiledDocument(
            node=cast("CompiledNode", node),
            stylesheets=cast("tuple[CompiledStyleSheet, ...]", compiled_stylesheets),
            images=document.images,
        )

    @_tracked("takumi.extension.compile_node")
    async def compile_node(
        self,
        node: NodeInput,
        *,
        validate: bool = False,
    ) -> CompiledNode:
        compiled = await self._state.call_renderer(
            "compile_node",
            node,
            validate=validate,
        )
        return cast("CompiledNode", compiled)

    @_tracked("takumi.extension.compile_stylesheet")
    async def compile_stylesheet(
        self,
        css: str,
        *,
        lossy: bool = False,
    ) -> CompiledStyleSheet:
        compiled = await self._state.compile_stylesheet(css, lossy=lossy)
        return cast("CompiledStyleSheet", compiled)

    @_tracked("takumi.extension.compile_keyframes")
    async def compile_keyframes(
        self,
        keyframes: KeyframesInput,
    ) -> CompiledStyleSheet:
        compiled = await self._state.call_renderer("compile_keyframes", keyframes)
        return cast("CompiledStyleSheet", compiled)

    @_tracked("takumi.extension.render_html")
    async def render_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        width: int | None = 1200,
        height: int | None = None,
        format: StaticImageFormat = "png",
        quality: int | None = None,
        lossless: bool | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> bytes:
        prepared = (
            html
            if isinstance(html, PreparedHtml)
            else prepare_html(html, base_url=base_url)
        )
        return await render_prepared_html(
            self._state,
            prepared,
            stylesheets=stylesheets,
            images=cast("Sequence[object] | None", images),
            width=width,
            height=height,
            image_format=format,
            quality=quality,
            lossless=lossless,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            lang=lang,
            font_families=font_families,
            keyframes=keyframes,
        )

    @_tracked("takumi.extension.render_compiled")
    async def render_compiled(
        self,
        document: TakumiCompiledDocument,
        *,
        width: int | None = 1200,
        height: int | None = None,
        format: StaticImageFormat = "png",
        quality: int | None = None,
        lossless: bool | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> bytes:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format=format,
            quality=quality,
            lossless=lossless,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            images=cast("Sequence[ImageInput]", document.images),
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        rendered = await self._state.call_renderer(
            "render_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **options,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.measure_html")
    async def measure_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        width: int | None = 1200,
        height: int | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> MeasuredNode:
        prepared = (
            html
            if isinstance(html, PreparedHtml)
            else prepare_html(html, base_url=base_url)
        )
        document = await materialize_takumi_document(
            prepared,
            stylesheets=stylesheets,
            images=cast("Sequence[object] | None", images),
        )
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format="png",
            quality=None,
            lossless=None,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            images=cast("Sequence[ImageInput]", document.images),
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        options.pop("format")
        measured = await self._state.call_document(
            "measure_compiled",
            document.html,
            document.stylesheets,
            **options,
        )
        return cast("MeasuredNode", measured)

    @_tracked("takumi.extension.measure_compiled")
    async def measure_compiled(
        self,
        document: TakumiCompiledDocument,
        *,
        width: int | None = 1200,
        height: int | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> MeasuredNode:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format="png",
            quality=None,
            lossless=None,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            images=cast("Sequence[ImageInput]", document.images),
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        options.pop("format")
        measured = await self._state.call_renderer(
            "measure_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **options,
        )
        return cast("MeasuredNode", measured)

    @_tracked("takumi.extension.render_svg_html")
    async def render_svg_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        time_ms: int = 0,
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> str:
        prepared = (
            html
            if isinstance(html, PreparedHtml)
            else prepare_html(html, base_url=base_url)
        )
        document = await materialize_takumi_document(
            prepared,
            stylesheets=stylesheets,
            images=cast("Sequence[object] | None", images),
        )
        options = _svg_kwargs(
            self._state,
            width=width,
            height=height,
            font_size=font_size,
            time_ms=time_ms,
            images=cast("Sequence[ImageInput]", document.images),
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        rendered = await self._state.call_document(
            "render_svg_compiled",
            document.html,
            document.stylesheets,
            **options,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_svg_compiled")
    async def render_svg_compiled(
        self,
        document: TakumiCompiledDocument,
        *,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        time_ms: int = 0,
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> str:
        options = _svg_kwargs(
            self._state,
            width=width,
            height=height,
            font_size=font_size,
            time_ms=time_ms,
            images=cast("Sequence[ImageInput]", document.images),
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        rendered = await self._state.call_renderer(
            "render_svg_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **options,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_node")
    async def render_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        format: StaticImageFormat = "png",
        quality: int | None = None,
        lossless: bool | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
        validate: bool = False,
    ) -> bytes:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format=format,
            quality=quality,
            lossless=lossless,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            images=images,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        rendered = await self._state.call_renderer(
            "render_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **options,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.measure_node")
    async def measure_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
        validate: bool = False,
    ) -> MeasuredNode:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format="png",
            quality=None,
            lossless=None,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            images=images,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        options.pop("format")
        measured = await self._state.call_renderer(
            "measure_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **options,
        )
        return cast("MeasuredNode", measured)

    @_tracked("takumi.extension.render_svg_node")
    async def render_svg_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        time_ms: int = 0,
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
        validate: bool = False,
    ) -> str:
        options = _svg_kwargs(
            self._state,
            width=width,
            height=height,
            font_size=font_size,
            time_ms=time_ms,
            images=images,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        rendered = await self._state.call_renderer(
            "render_svg_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **options,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_animation")
    async def render_animation(
        self,
        scenes: Sequence[AnimationScene],
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
        fps: int = 30,
        format: AnimationImageFormat = "webp",
        quality: int | None = None,
        lossless: bool | None = None,
        loop_count: int | None = None,
        webp_blend: bool = True,
        webp_dispose: bool = False,
        webp_speed: int | None = None,
        validate: bool = False,
    ) -> bytes:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format="png",
            quality=None,
            lossless=None,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=0,
            dithering=dithering,
            images=images,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        options.pop("format")
        options.pop("time_ms")
        options.update(
            fps=fps,
            format=format,
            webp_blend=webp_blend,
            webp_dispose=webp_dispose,
            validate=validate,
        )
        if quality is not None:
            options["quality"] = quality
        if lossless is not None:
            options["lossless"] = lossless
        if loop_count is not None:
            options["loop_count"] = loop_count
        if webp_speed is not None:
            options["webp_speed"] = webp_speed
        rendered = await self._state.call_renderer(
            "render_animation",
            tuple(scenes),
            stylesheets=tuple(stylesheets),
            **options,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.render_sequence")
    async def render_sequence_at_time(
        self,
        scenes: Sequence[AnimationScene],
        time_ms: int,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        format: StaticImageFormat = "png",
        quality: int | None = None,
        lossless: bool | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
        validate: bool = False,
    ) -> bytes:
        options = _raster_kwargs(
            self._state,
            width=width,
            height=height,
            format=format,
            quality=quality,
            lossless=lossless,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=0,
            dithering=dithering,
            images=images,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )
        options.pop("time_ms")
        options["validate"] = validate
        rendered = await self._state.call_renderer(
            "render_sequence_at_time",
            tuple(scenes),
            time_ms,
            stylesheets=tuple(stylesheets),
            **options,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.encode_frames")
    async def encode_frames(
        self,
        frames: Sequence[RawAnimationFrame],
        *,
        format: AnimationImageFormat = "webp",
        quality: int | None = None,
        lossless: bool | None = None,
        loop_count: int | None = None,
        webp_blend: bool = True,
        webp_dispose: bool = False,
        webp_speed: int | None = None,
    ) -> bytes:
        options: dict[str, object] = {
            "format": format,
            "webp_blend": webp_blend,
            "webp_dispose": webp_dispose,
        }
        if quality is not None:
            options["quality"] = quality
        if lossless is not None:
            options["lossless"] = lossless
        if loop_count is not None:
            options["loop_count"] = loop_count
        if webp_speed is not None:
            options["webp_speed"] = webp_speed
        rendered = await self._state.call_renderer(
            "encode_frames",
            tuple(frames),
            **options,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.register_font")
    async def register_font(
        self,
        font: FontResourceInput,
        *,
        source: str | None = None,
    ) -> tuple[str, ...]:
        return await self._state.register_font(font, source=source)

    @_tracked("takumi.extension.register_fonts")
    async def register_fonts(
        self,
        fonts: Sequence[FontResourceInput],
        *,
        sources: Sequence[str | None] | None = None,
    ) -> tuple[str, ...]:
        return await self._state.register_fonts(
            cast("Sequence[object]", fonts),
            sources=sources,
        )

    @_tracked("takumi.extension.register_font_file")
    async def register_font_file(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        weight: float | None = None,
        style: str | None = None,
        subset_of: str | None = None,
        generic_family: Literal[
            "serif",
            "sans-serif",
            "monospace",
            "cursive",
            "fantasy",
            "system-ui",
            "ui-serif",
            "ui-sans-serif",
            "ui-monospace",
            "ui-rounded",
            "emoji",
            "math",
            "fangsong",
        ]
        | None = None,
        cache_policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    ) -> tuple[str, ...]:
        return await self._state.register_font_file(
            path,
            name=name,
            weight=weight,
            style=style,
            subset_of=subset_of,
            generic_family=generic_family,
            cache_policy=cache_policy,
        )

    @_tracked("takumi.extension.render_template")
    async def render_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = None,
        format: StaticImageFormat = "png",
        quality: int | None = None,
        lossless: bool | None = None,
        font_size: float = 16.0,
        device_pixel_ratio: float = 1.0,
        draw_debug_border: bool = False,
        time_ms: int = 0,
        dithering: DitheringAlgorithm = "none",
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> bytes:
        prepared = await prepare_template(
            template_path,
            template_name,
            variables,
            filters=filters,
        )
        return await self.render_html(
            prepared,
            stylesheets=stylesheets,
            images=images,
            width=width,
            height=height,
            format=format,
            quality=quality,
            lossless=lossless,
            font_size=font_size,
            device_pixel_ratio=device_pixel_ratio,
            draw_debug_border=draw_debug_border,
            time_ms=time_ms,
            dithering=dithering,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )

    @_tracked("takumi.extension.render_svg_template")
    async def render_svg_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        width: int | None = 1200,
        height: int | None = 630,
        font_size: float = 16.0,
        time_ms: int = 0,
        keyframes: KeyframesInput | None = None,
        font_families: Sequence[str] | None = None,
        lang: str | None = None,
    ) -> str:
        prepared = await prepare_template(
            template_path,
            template_name,
            variables,
            filters=filters,
        )
        return await self.render_svg_html(
            prepared,
            stylesheets=stylesheets,
            images=images,
            width=width,
            height=height,
            font_size=font_size,
            time_ms=time_ms,
            keyframes=keyframes,
            font_families=font_families,
            lang=lang,
        )


TAKUMI_EXTENSION = BackendExtension("takumi.v1", TakumiExtension)


__all__ = [
    "TAKUMI_EXTENSION",
    "TakumiCompiledDocument",
    "TakumiExtension",
    "TakumiImageResource",
]
