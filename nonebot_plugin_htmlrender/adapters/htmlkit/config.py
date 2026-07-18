"""Configuration owned by the HTMLKit provider adapter."""

from __future__ import annotations

from os import cpu_count
from typing import ClassVar

from nonebot.compat import field_validator
from pydantic import BaseModel, ConfigDict, Field

from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode


def _default_concurrency() -> int:
    return max(1, min(cpu_count() or 1, 4))


class HtmlkitConfig(BaseModel):
    """HTMLKit settings under ``render.provider_config``.

    ``media_dpi`` and ``media_height`` are CSS media-environment inputs.  They
    are deliberately not named as raster scale or output height because
    HTMLKit rc5 does not implement either of those portable semantics.
    """

    max_concurrency: int = Field(default_factory=_default_concurrency, ge=1, le=64)
    default_font_size: float = Field(default=12.0, gt=0)
    font_name: str = "sans-serif"
    language: str = "zh"
    culture: str = "CN"
    media_dpi: float = Field(default=96.0, gt=0)
    media_height: float = Field(default=600.0, gt=0)
    resource_resolve_mode: ResourceResolveMode = ResourceResolveMode.AUTO

    model_config: ClassVar[ConfigDict] = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        validate_assignment=True,
    )

    @field_validator("font_name", "language", "culture", mode="before")
    @classmethod
    def _nonempty_text(cls, value: object) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            raise ValueError("value must not be empty")
        return text


__all__ = ["HtmlkitConfig"]
