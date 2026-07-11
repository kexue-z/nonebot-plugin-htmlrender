from __future__ import annotations

from os import cpu_count
from pathlib import Path
from typing import Literal

from nonebot import get_plugin_config
from nonebot.compat import field_validator
from pydantic import BaseModel, ConfigDict, Field

from nonebot_plugin_htmlrender.resources import FileCachePolicy

GenericFontFamily = Literal[
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


def _default_concurrency() -> int:
    return max(1, min(cpu_count() or 1, 4))


class TakumiFontConfig(BaseModel):
    """One font registered in the process-local Takumi renderer."""

    path: Path
    name: str | None = None
    weight: float | None = Field(default=None, ge=1, le=1000)
    style: str | None = None
    subset_of: str | None = None
    generic_family: GenericFontFamily | None = None
    cache_policy: FileCachePolicy | None = None

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: object) -> Path:
        text = str(value).strip() if value is not None else ""
        if not text or text == ".":
            raise ValueError("font path must not be empty")
        return Path(text).expanduser()

    @field_validator("name", "style", "subset_of", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class TakumiHtmlOptionsConfig(BaseModel):
    """Options forwarded to Takumi's Rust-backed HTML parser."""

    presets: Literal["chromium", "none"] = "chromium"
    tailwind_property: str | None = None
    max_depth: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("tailwind_property", mode="before")
    @classmethod
    def _normalize_tailwind_property(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class TakumiConfig(BaseModel):
    """Takumi backend configuration under the ``render_takumi`` namespace."""

    load_default_fonts: bool = True
    fonts: list[TakumiFontConfig] = Field(default_factory=list)
    font_cache_policy: FileCachePolicy = FileCachePolicy.REVALIDATE
    max_concurrency: int = Field(default_factory=_default_concurrency, ge=1, le=64)
    compiled_cache_max_entries: int = Field(default=128, ge=0, le=4096)
    compiled_cache_max_bytes: int = Field(
        default=32 * 1024 * 1024,
        ge=0,
    )
    html_options: TakumiHtmlOptionsConfig = Field(
        default_factory=TakumiHtmlOptionsConfig
    )
    default_lang: str | None = None
    font_families: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("default_lang", mode="before")
    @classmethod
    def _normalize_default_lang(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("font_families", mode="before")
    @classmethod
    def _normalize_font_families(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class TakumiPluginConfig(BaseModel):
    """NoneBot configuration namespace for the Takumi backend."""

    render_takumi: TakumiConfig = Field(default_factory=TakumiConfig)


def get_takumi_config() -> TakumiConfig:
    return get_plugin_config(TakumiPluginConfig).render_takumi


__all__ = [
    "GenericFontFamily",
    "TakumiConfig",
    "TakumiFontConfig",
    "TakumiHtmlOptionsConfig",
    "TakumiPluginConfig",
    "get_takumi_config",
]
