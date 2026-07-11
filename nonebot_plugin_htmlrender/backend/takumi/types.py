from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias

ImageCacheMode: TypeAlias = Literal["auto", "none"]
StaticImageFormat: TypeAlias = Literal["png", "jpeg", "jpg", "webp", "ico", "raw"]
AnimationImageFormat: TypeAlias = Literal["webp", "apng", "gif"]


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


class NativeRenderer(Protocol):
    def compile_html(self, html: str, **kwargs: Any) -> NativeCompiledHtml: ...

    def compile_stylesheet(self, css: str) -> object: ...

    def compile_stylesheet_lossy(self, css: str) -> object: ...

    def render_compiled(self, node: object, **kwargs: Any) -> bytes: ...

    def measure_compiled(self, node: object, **kwargs: Any) -> object: ...

    def render_svg_compiled(self, node: object, **kwargs: Any) -> str: ...

    def render_node(self, node: object, **kwargs: Any) -> bytes: ...

    def measure_node(self, node: object, **kwargs: Any) -> object: ...

    def render_svg_node(self, node: object, **kwargs: Any) -> str: ...

    def render_animation(self, scenes: object, **kwargs: Any) -> bytes: ...

    def render_sequence_at_time(
        self, scenes: object, time_ms: int, **kwargs: Any
    ) -> bytes: ...

    def encode_frames(self, frames: object, **kwargs: Any) -> bytes: ...

    def register_font(self, font: object) -> tuple[str, ...]: ...

    def register_fonts(self, fonts: object) -> tuple[str, ...]: ...


class NativeCompiledHtml(Protocol):
    node: object


__all__ = [
    "AnimationImageFormat",
    "ImageCacheMode",
    "NativeCompiledHtml",
    "NativeRenderer",
    "StaticImageFormat",
    "TakumiImageInput",
    "TakumiImageResource",
    "TakumiImageResourceLike",
]
