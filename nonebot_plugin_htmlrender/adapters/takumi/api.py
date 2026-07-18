from __future__ import annotations

# Keep Takumi's public ``format=`` spelling in the typed extension API.
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Awaitable, Callable, ParamSpec, TypeVar, cast

from nonebot_plugin_htmlrender.capabilities.takumi import (
    FileCachePolicy,
    TakumiCompiledDocument,
)
from nonebot_plugin_htmlrender.preparation import PreparedHtml, prepare_html
from nonebot_plugin_htmlrender.rendering.observers import (
    NoopOperationObserver,
    observe_operation,
)

from .operations import (
    device_dimension,
    render_prepared_html,
    validate_device_pixel_ratio,
)
from .runtime import TakumiRuntimeState, render_defaults
from .source import materialize_takumi_document
from .types import TakumiImageResource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from typing_extensions import Unpack

    from takumi_py import (
        AnimationScene,
        CompiledNode,
        CompiledStyleSheet,
        FontResourceInput,
        KeyframesInput,
        MeasuredNode,
        NodeInput,
        RawAnimationFrame,
    )

    from nonebot_plugin_htmlrender.capabilities.takumi import (
        GenericFontFamily,
        ImageInput,
        TakumiAnimationOptions,
        TakumiCacheStats,
        TakumiFrameEncodeOptions,
        TakumiMeasureOptions,
        TakumiRasterOptions,
        TakumiSequenceOptions,
        TakumiSvgOptions,
    )
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver

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
            with observe_operation(
                extension._observer,
                operation,
                {"render.backend": "takumi"},
            ):
                extension._state._ensure_open()
                return await func(*args, **kwargs)

        return _wrapped

    return _decorate


def _apply_present(
    native: dict[str, object],
    options: Mapping[str, object],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = options.get(key)
        if value is not None:
            native[key] = value


def _apply_font_families(
    native: dict[str, object],
    families: Sequence[str] | None,
) -> None:
    if families is not None:
        native["font_families"] = tuple(families)


def _static_raster_kwargs(
    state: TakumiRuntimeState,
    options: TakumiRasterOptions | TakumiSequenceOptions,
    *,
    default_height: int | None,
    images: Sequence[ImageInput] | None,
    include_time: bool = True,
) -> dict[str, object]:
    ratio = validate_device_pixel_ratio(options.get("device_pixel_ratio", 1.0))
    native = render_defaults(state, images=images)
    native.update(
        width=device_dimension(options.get("width", 1200), ratio),
        height=device_dimension(options.get("height", default_height), ratio),
        format=options.get("format", "png"),
        font_size=options.get("font_size", 16.0),
        device_pixel_ratio=ratio,
        draw_debug_border=options.get("draw_debug_border", False),
        dithering=options.get("dithering", "none"),
    )
    if include_time:
        native["time_ms"] = cast("TakumiRasterOptions", options).get("time_ms", 0)
    _apply_present(native, options, ("quality", "lossless", "keyframes", "lang"))
    _apply_font_families(native, options.get("font_families"))
    return native


def _measure_kwargs(
    state: TakumiRuntimeState,
    options: TakumiMeasureOptions,
    *,
    default_height: int | None,
    images: Sequence[ImageInput] | None,
) -> dict[str, object]:
    ratio = validate_device_pixel_ratio(options.get("device_pixel_ratio", 1.0))
    native = render_defaults(state, images=images)
    native.update(
        width=device_dimension(options.get("width", 1200), ratio),
        height=device_dimension(options.get("height", default_height), ratio),
        font_size=options.get("font_size", 16.0),
        device_pixel_ratio=ratio,
        draw_debug_border=options.get("draw_debug_border", False),
        time_ms=options.get("time_ms", 0),
        dithering=options.get("dithering", "none"),
    )
    _apply_present(native, options, ("keyframes", "lang"))
    _apply_font_families(native, options.get("font_families"))
    return native


def _svg_kwargs(
    state: TakumiRuntimeState,
    options: TakumiSvgOptions,
    *,
    images: Sequence[ImageInput] | None,
) -> dict[str, object]:
    native = render_defaults(state, images=images)
    native.update(
        width=options.get("width", 1200),
        height=options.get("height", 630),
        font_size=options.get("font_size", 16.0),
        time_ms=options.get("time_ms", 0),
    )
    _apply_present(native, options, ("keyframes", "lang"))
    _apply_font_families(native, options.get("font_families"))
    return native


def _frame_encode_kwargs(options: TakumiFrameEncodeOptions) -> dict[str, object]:
    native: dict[str, object] = {
        "format": options.get("format", "webp"),
        "webp_blend": options.get("webp_blend", True),
        "webp_dispose": options.get("webp_dispose", False),
    }
    _apply_present(native, options, ("quality", "lossless", "loop_count", "webp_speed"))
    return native


def _animation_kwargs(
    state: TakumiRuntimeState,
    options: TakumiAnimationOptions,
    *,
    images: Sequence[ImageInput] | None,
) -> dict[str, object]:
    ratio = validate_device_pixel_ratio(options.get("device_pixel_ratio", 1.0))
    native = render_defaults(state, images=images)
    native.update(
        width=device_dimension(options.get("width", 1200), ratio),
        height=device_dimension(options.get("height", 630), ratio),
        font_size=options.get("font_size", 16.0),
        device_pixel_ratio=ratio,
        draw_debug_border=options.get("draw_debug_border", False),
        dithering=options.get("dithering", "none"),
        fps=options.get("fps", 30),
    )
    native.update(_frame_encode_kwargs(options))
    _apply_present(native, options, ("keyframes", "lang"))
    _apply_font_families(native, options.get("font_families"))
    return native


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
    _observer: OperationObserver = field(
        default_factory=NoopOperationObserver,
        repr=False,
        compare=False,
    )

    @property
    def registered_font_families(self) -> tuple[str, ...]:
        return self._state.registered_font_families

    @property
    def compiled_cache_stats(self) -> TakumiCacheStats:
        """Return an immutable snapshot of this runtime's compiled cache."""

        return self._state.compiled_cache_stats

    def _prepared(self, html: str | PreparedHtml, base_url: str | None) -> PreparedHtml:
        if isinstance(html, PreparedHtml):
            return html
        return prepare_html(html, base_url=base_url)

    @_tracked("takumi.extension.compile_html")
    async def compile_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
    ) -> TakumiCompiledDocument:
        document = await materialize_takumi_document(
            self._prepared(html, base_url),
            resources=self._state.resources,
            stylesheets=stylesheets,
            images=images,
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
        **options: Unpack[TakumiRasterOptions],
    ) -> bytes:
        return await render_prepared_html(
            self._state,
            self._prepared(html, base_url),
            stylesheets=stylesheets,
            images=images,
            width=options.get("width", 1200),
            height=options.get("height"),
            image_format=options.get("format", "png"),
            quality=options.get("quality"),
            lossless=options.get("lossless"),
            font_size=options.get("font_size", 16.0),
            device_pixel_ratio=options.get("device_pixel_ratio", 1.0),
            draw_debug_border=options.get("draw_debug_border", False),
            time_ms=options.get("time_ms", 0),
            dithering=options.get("dithering", "none"),
            lang=options.get("lang"),
            font_families=options.get("font_families"),
            keyframes=options.get("keyframes"),
        )

    @_tracked("takumi.extension.render_compiled")
    async def render_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiRasterOptions],
    ) -> bytes:
        native = _static_raster_kwargs(
            self._state,
            options,
            default_height=None,
            images=cast("Sequence[ImageInput]", document.images),
        )
        rendered = await self._state.call_renderer(
            "render_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **native,
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
        **options: Unpack[TakumiMeasureOptions],
    ) -> MeasuredNode:
        document = await materialize_takumi_document(
            self._prepared(html, base_url),
            resources=self._state.resources,
            stylesheets=stylesheets,
            images=images,
        )
        native = _measure_kwargs(
            self._state,
            options,
            default_height=None,
            images=cast("Sequence[ImageInput]", document.images),
        )
        measured = await self._state.call_document(
            "measure_compiled",
            document.html,
            document.stylesheets,
            **native,
        )
        return cast("MeasuredNode", measured)

    @_tracked("takumi.extension.measure_compiled")
    async def measure_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiMeasureOptions],
    ) -> MeasuredNode:
        native = _measure_kwargs(
            self._state,
            options,
            default_height=None,
            images=cast("Sequence[ImageInput]", document.images),
        )
        measured = await self._state.call_renderer(
            "measure_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **native,
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
        **options: Unpack[TakumiSvgOptions],
    ) -> str:
        document = await materialize_takumi_document(
            self._prepared(html, base_url),
            resources=self._state.resources,
            stylesheets=stylesheets,
            images=images,
        )
        native = _svg_kwargs(
            self._state,
            options,
            images=cast("Sequence[ImageInput]", document.images),
        )
        rendered = await self._state.call_document(
            "render_svg_compiled",
            document.html,
            document.stylesheets,
            **native,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_svg_compiled")
    async def render_svg_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiSvgOptions],
    ) -> str:
        native = _svg_kwargs(
            self._state,
            options,
            images=cast("Sequence[ImageInput]", document.images),
        )
        rendered = await self._state.call_renderer(
            "render_svg_compiled",
            document.node,
            stylesheets=document.stylesheets,
            **native,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_node")
    async def render_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiRasterOptions],
    ) -> bytes:
        native = _static_raster_kwargs(
            self._state,
            options,
            default_height=630,
            images=images,
        )
        rendered = await self._state.call_renderer(
            "render_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **native,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.measure_node")
    async def measure_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiMeasureOptions],
    ) -> MeasuredNode:
        native = _measure_kwargs(
            self._state,
            options,
            default_height=630,
            images=images,
        )
        measured = await self._state.call_renderer(
            "measure_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **native,
        )
        return cast("MeasuredNode", measured)

    @_tracked("takumi.extension.render_svg_node")
    async def render_svg_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiSvgOptions],
    ) -> str:
        native = _svg_kwargs(self._state, options, images=images)
        rendered = await self._state.call_renderer(
            "render_svg_node",
            node,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **native,
        )
        return _expect_svg(rendered)

    @_tracked("takumi.extension.render_animation")
    async def render_animation(
        self,
        scenes: Sequence[AnimationScene],
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiAnimationOptions],
    ) -> bytes:
        native = _animation_kwargs(self._state, options, images=images)
        rendered = await self._state.call_renderer(
            "render_animation",
            tuple(scenes),
            stylesheets=tuple(stylesheets),
            validate=validate,
            **native,
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
        validate: bool = False,
        **options: Unpack[TakumiSequenceOptions],
    ) -> bytes:
        native = _static_raster_kwargs(
            self._state,
            options,
            default_height=630,
            images=images,
            include_time=False,
        )
        rendered = await self._state.call_renderer(
            "render_sequence_at_time",
            tuple(scenes),
            time_ms,
            stylesheets=tuple(stylesheets),
            validate=validate,
            **native,
        )
        return _expect_bytes(rendered)

    @_tracked("takumi.extension.encode_frames")
    async def encode_frames(
        self,
        frames: Sequence[RawAnimationFrame],
        **options: Unpack[TakumiFrameEncodeOptions],
    ) -> bytes:
        rendered = await self._state.call_renderer(
            "encode_frames",
            tuple(frames),
            **_frame_encode_kwargs(options),
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
        generic_family: GenericFontFamily | None = None,
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


__all__ = [
    "TakumiCompiledDocument",
    "TakumiExtension",
    "TakumiImageResource",
]
