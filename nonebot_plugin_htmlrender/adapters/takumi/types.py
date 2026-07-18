from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.capabilities.takumi import (
    AnimationImageFormat as AnimationImageFormat,
)
from nonebot_plugin_htmlrender.capabilities.takumi import (
    ImageCacheMode as ImageCacheMode,
)
from nonebot_plugin_htmlrender.capabilities.takumi import (
    StaticImageFormat as StaticImageFormat,
)
from nonebot_plugin_htmlrender.capabilities.takumi import (
    TakumiImageInput as TakumiImageInput,
)
from nonebot_plugin_htmlrender.capabilities.takumi import (
    TakumiImageResource as TakumiImageResource,
)
from nonebot_plugin_htmlrender.capabilities.takumi import (
    TakumiImageResourceLike as TakumiImageResourceLike,
)

if TYPE_CHECKING:
    from typing import TypeAlias

    from takumi_py import CompiledHtml, Renderer

    NativeCompiledHtml: TypeAlias = CompiledHtml
    NativeRenderer: TypeAlias = Renderer

__all__ = [
    "AnimationImageFormat",
    "ImageCacheMode",
    "StaticImageFormat",
    "TakumiImageInput",
    "TakumiImageResource",
    "TakumiImageResourceLike",
]
