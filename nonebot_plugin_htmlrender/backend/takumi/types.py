from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

if TYPE_CHECKING:
    from takumi_py import CompiledHtml, Renderer

    NativeCompiledHtml: TypeAlias = CompiledHtml
    NativeRenderer: TypeAlias = Renderer

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


__all__ = [
    "AnimationImageFormat",
    "ImageCacheMode",
    "StaticImageFormat",
    "TakumiImageInput",
    "TakumiImageResource",
    "TakumiImageResourceLike",
]
