"""Stable public contract for Takumi-specific operations.

This module owns the neutral vocabulary of the Takumi capability: image and
font value types, the keyword-option groups shared by the render/measure/svg
variants, and the typed extension surface leased to callers.  It never
depends on adapter modules; ``takumi_py`` types appear only in annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from typing_extensions import TypeAlias, TypedDict

from nonebot_plugin_htmlrender._typing import (
    identity_decorator,
    project_method_parameters,
)
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityKey

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path
    from typing_extensions import Unpack

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
        Renderer,
    )

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml

if TYPE_CHECKING:
    _compile_node_signature = project_method_parameters(Renderer.compile_node)
    _compile_keyframes_signature = project_method_parameters(Renderer.compile_keyframes)
else:
    _compile_node_signature = identity_decorator
    _compile_keyframes_signature = identity_decorator


ImageCacheMode: TypeAlias = Literal["auto", "none"]
StaticImageFormat: TypeAlias = Literal["png", "jpeg", "jpg", "webp", "ico", "raw"]
AnimationImageFormat: TypeAlias = Literal["webp", "apng", "gif"]
GenericFontFamily: TypeAlias = Literal[
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


class FileCachePolicy(str, Enum):
    """Validation policy for user-provided Takumi font files."""

    IMMUTABLE = "immutable"
    REVALIDATE = "revalidate"


@dataclass(frozen=True, slots=True)
class TakumiImageResource:
    """An image made available under an exact HTML/CSS source key."""

    src: str
    data: bytes
    cache: ImageCacheMode = "auto"


class TakumiImageResourceLike(Protocol):
    """Promised image duck type accepted without a takumi-py import."""

    src: str
    data: bytes


TakumiImageInput: TypeAlias = (
    TakumiImageResource | tuple[str, bytes] | TakumiImageResourceLike
)

if TYPE_CHECKING:
    ImageInput: TypeAlias = ImageResourceInput | TakumiImageResource
else:
    ImageInput: TypeAlias = object


@dataclass(frozen=True, slots=True)
class TakumiCompiledDocument:
    """A compiled document tied to the renderer owned by one Takumi runtime."""

    node: CompiledNode
    stylesheets: tuple[CompiledStyleSheet, ...]
    images: tuple[ImageInput, ...] = ()


class TakumiCacheStats(Protocol):
    """Read-only snapshot of the runtime's compiled-document cache."""

    @property
    def entries(self) -> int: ...

    @property
    def resident_weight(self) -> int: ...

    @property
    def hits(self) -> int: ...

    @property
    def misses(self) -> int: ...

    @property
    def loads(self) -> int: ...

    @property
    def waits(self) -> int: ...

    @property
    def evictions(self) -> int: ...


class TakumiRasterOptions(TypedDict, total=False):
    """Raster options shared by every static image render variant.

    ``width``/``height`` are CSS pixels; the adapter converts them to
    Takumi's device-pixel canvas using ``device_pixel_ratio``.  Defaults:
    ``width=1200``, ``format="png"``, ``font_size=16.0``,
    ``device_pixel_ratio=1.0``, ``time_ms=0``, ``dithering="none"``; the
    default height is ``None`` for html variants and ``630`` for node/scene
    variants.
    """

    width: int | None
    height: int | None
    format: StaticImageFormat
    quality: int | None
    lossless: bool | None
    font_size: float
    device_pixel_ratio: float
    draw_debug_border: bool
    time_ms: int
    dithering: DitheringAlgorithm
    keyframes: KeyframesInput | None
    font_families: Sequence[str] | None
    lang: str | None


class TakumiMeasureOptions(TypedDict, total=False):
    """Layout-measurement options: raster options minus encoding knobs."""

    width: int | None
    height: int | None
    font_size: float
    device_pixel_ratio: float
    draw_debug_border: bool
    time_ms: int
    dithering: DitheringAlgorithm
    keyframes: KeyframesInput | None
    font_families: Sequence[str] | None
    lang: str | None


class TakumiSvgOptions(TypedDict, total=False):
    """Vector output options; dimensions stay in CSS pixels."""

    width: int | None
    height: int | None
    font_size: float
    time_ms: int
    keyframes: KeyframesInput | None
    font_families: Sequence[str] | None
    lang: str | None


class TakumiFrameEncodeOptions(TypedDict, total=False):
    """Animation container encoding knobs shared with ``encode_frames``."""

    format: AnimationImageFormat
    quality: int | None
    lossless: bool | None
    loop_count: int | None
    webp_blend: bool
    webp_dispose: bool
    webp_speed: int | None


class TakumiAnimationOptions(TakumiFrameEncodeOptions, total=False):
    """Scene rendering plus container encoding for ``render_animation``."""

    width: int | None
    height: int | None
    font_size: float
    device_pixel_ratio: float
    draw_debug_border: bool
    dithering: DitheringAlgorithm
    keyframes: KeyframesInput | None
    font_families: Sequence[str] | None
    lang: str | None
    fps: int


class TakumiSequenceOptions(TypedDict, total=False):
    """Raster options for one animation timestamp (``time_ms`` positional)."""

    width: int | None
    height: int | None
    format: StaticImageFormat
    quality: int | None
    lossless: bool | None
    font_size: float
    device_pixel_ratio: float
    draw_debug_border: bool
    dithering: DitheringAlgorithm
    keyframes: KeyframesInput | None
    font_families: Sequence[str] | None
    lang: str | None


class TakumiAPI(Protocol):
    """Managed Takumi operations leased for the lifetime of one context."""

    @property
    def registered_font_families(self) -> tuple[str, ...]: ...

    @property
    def compiled_cache_stats(self) -> TakumiCacheStats: ...

    def compile_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
    ) -> Awaitable[TakumiCompiledDocument]: ...

    @_compile_node_signature
    def compile_node(self, *args: Any, **kwargs: Any) -> Awaitable[CompiledNode]: ...

    def compile_stylesheet(
        self,
        css: str,
        *,
        lossy: bool = False,
    ) -> Awaitable[CompiledStyleSheet]: ...

    @_compile_keyframes_signature
    def compile_keyframes(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[CompiledStyleSheet]: ...

    def render_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        **options: Unpack[TakumiRasterOptions],
    ) -> Awaitable[bytes]: ...

    def render_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiRasterOptions],
    ) -> Awaitable[bytes]: ...

    def measure_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        **options: Unpack[TakumiMeasureOptions],
    ) -> Awaitable[MeasuredNode]: ...

    def measure_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiMeasureOptions],
    ) -> Awaitable[MeasuredNode]: ...

    def render_svg_html(
        self,
        html: str | PreparedHtml,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        base_url: str | None = None,
        **options: Unpack[TakumiSvgOptions],
    ) -> Awaitable[str]: ...

    def render_svg_compiled(
        self,
        document: TakumiCompiledDocument,
        **options: Unpack[TakumiSvgOptions],
    ) -> Awaitable[str]: ...

    def render_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiRasterOptions],
    ) -> Awaitable[bytes]: ...

    def measure_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiMeasureOptions],
    ) -> Awaitable[MeasuredNode]: ...

    def render_svg_node(
        self,
        node: NodeInput,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiSvgOptions],
    ) -> Awaitable[str]: ...

    def render_animation(
        self,
        scenes: Sequence[AnimationScene],
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiAnimationOptions],
    ) -> Awaitable[bytes]: ...

    def render_sequence_at_time(
        self,
        scenes: Sequence[AnimationScene],
        time_ms: int,
        *,
        stylesheets: Sequence[str] = (),
        images: Sequence[ImageInput] | None = None,
        validate: bool = False,
        **options: Unpack[TakumiSequenceOptions],
    ) -> Awaitable[bytes]: ...

    def encode_frames(
        self,
        frames: Sequence[RawAnimationFrame],
        **options: Unpack[TakumiFrameEncodeOptions],
    ) -> Awaitable[bytes]: ...

    def register_font(
        self,
        font: FontResourceInput,
        *,
        source: str | None = None,
    ) -> Awaitable[tuple[str, ...]]: ...

    def register_fonts(
        self,
        fonts: Sequence[FontResourceInput],
        *,
        sources: Sequence[str | None] | None = None,
    ) -> Awaitable[tuple[str, ...]]: ...

    def register_font_file(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        weight: float | None = None,
        style: str | None = None,
        subset_of: str | None = None,
        generic_family: GenericFontFamily | None = None,
        cache_policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    ) -> Awaitable[tuple[str, ...]]: ...


@runtime_checkable
class TakumiAccess(Protocol):
    """Lease managed or raw objects from the provider-owned Takumi runtime."""

    def api(self) -> AbstractAsyncContextManager[TakumiAPI]: ...

    def renderer(self) -> AbstractAsyncContextManager[Renderer]: ...


TAKUMI: CapabilityKey[TakumiAccess] = CapabilityKey(
    "takumi",
    TakumiAccess,
)

__all__ = [
    "TAKUMI",
    "AnimationImageFormat",
    "FileCachePolicy",
    "GenericFontFamily",
    "ImageCacheMode",
    "ImageInput",
    "StaticImageFormat",
    "TakumiAPI",
    "TakumiAccess",
    "TakumiAnimationOptions",
    "TakumiCacheStats",
    "TakumiCompiledDocument",
    "TakumiFrameEncodeOptions",
    "TakumiImageInput",
    "TakumiImageResource",
    "TakumiImageResourceLike",
    "TakumiMeasureOptions",
    "TakumiRasterOptions",
    "TakumiSequenceOptions",
    "TakumiSvgOptions",
]
