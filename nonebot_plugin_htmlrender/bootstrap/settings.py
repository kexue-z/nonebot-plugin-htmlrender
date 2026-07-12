"""Unified ``render`` configuration tree and legacy-key detection."""

from __future__ import annotations

from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nonebot_plugin_htmlrender.consts import RenderStartupMode


class _StrictRenderModel(BaseModel):
    """Reject misspelled keys inside the plugin-owned ``render`` tree."""

    model_config = ConfigDict(extra="forbid")


class CacheSettings(_StrictRenderModel):
    """Sizing of the shared resource cache budget."""

    max_entries: int = Field(default=256, ge=0)
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=0)
    max_resource_bytes: int = Field(default=64 * 1024 * 1024, ge=0)
    revalidate_seconds: float = Field(default=1.0, ge=0.0)


class TemplateSettings(_StrictRenderModel):
    """Sizing of the template environment cache."""

    environment_cache_max_entries: int = Field(default=64, ge=0)


class LocalAccessSettings(_StrictRenderModel):
    """Security policy for local filesystem resource access."""

    allow_any_path: bool = Field(default=False)
    allowed_paths: list[Path] = Field(default_factory=list)

    @field_validator("allowed_paths", mode="before")
    @classmethod
    def _normalize_allowed_paths(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, (str, Path)):
            return [v]
        return v


class FilehostSettings(_StrictRenderModel):
    """Core-owned settings for the optional asset publisher adapter."""

    cache_ttl_seconds: float = Field(default=300.0, ge=0.0)
    request_header_name: str = Field(default="X-HTMLRender-Filehost-Request")
    request_header_value: str | None = Field(default=None)
    request_header_salt: str = Field(
        default="nonebot-plugin-htmlrender:filehost:guard:v1"
    )
    prewarm_enabled: bool = Field(default=True)
    prewarm_max_files: int = Field(default=256, ge=0)
    prewarm_paths: list[Path] = Field(default_factory=list)
    prewarm_extensions: list[str] = Field(default_factory=list)


class ObservabilitySettings(_StrictRenderModel):
    """Which observability integrations this plugin exports to."""

    sentry: bool = Field(default=False)
    prometheus: bool = Field(default=False)


class ResourceSettings(_StrictRenderModel):
    """Core-validated resource, cache, and security configuration."""

    cache: CacheSettings = Field(default_factory=CacheSettings)
    templates: TemplateSettings = Field(default_factory=TemplateSettings)
    local_access: LocalAccessSettings = Field(default_factory=LocalAccessSettings)
    filehost: FilehostSettings = Field(default_factory=FilehostSettings)


class RenderSettings(_StrictRenderModel):
    """The whole ``render`` configuration namespace."""

    provider: str | None = Field(default=None)
    startup: RenderStartupMode = Field(default=RenderStartupMode.OFF)
    provider_config: dict[str, object] = Field(default_factory=dict)
    resources: ResourceSettings = Field(default_factory=ResourceSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


class RenderPluginConfig(BaseModel):
    """NoneBot plugin configuration entry point."""

    # ``get_plugin_config`` validates this wrapper against the complete NoneBot
    # configuration, so unrelated top-level plugin keys must remain accepted.
    model_config = ConfigDict(extra="ignore")

    render: RenderSettings = Field(default_factory=RenderSettings)


LEGACY_CONFIG_KEYS: tuple[str, ...] = (
    "render_backend",
    "render_startup_mode",
    "render_playwright",
    "render_takumi",
    "render_storage_path",
    "render_cache_path",
    "render_config_path",
    "render_resource_cache_max_entries",
    "render_resource_cache_max_bytes",
    "render_resource_cache_revalidate_seconds",
    "render_template_environment_cache_max_entries",
)

_MIGRATION_HINT = (
    "nonebot-plugin-htmlrender 0.8 replaced the flat render_* keys with the "
    "unified `render` namespace (render.provider, render.startup, "
    "render.provider_config, render.resources, render.observability). "
    "See the 0.8 migration guide."
)


def detect_legacy_render_keys(config: object) -> tuple[str, ...]:
    """Return the legacy 0.7 keys still present on the driver config."""
    return tuple(
        key for key in LEGACY_CONFIG_KEYS if getattr(config, key, None) is not None
    )


def assert_no_legacy_render_keys(config: object) -> None:
    """Fail startup loudly when 0.7 configuration keys are detected."""
    found = detect_legacy_render_keys(config)
    if found:
        raise RuntimeError(
            f"Unsupported 0.7 configuration keys detected: {', '.join(found)}. "
            + _MIGRATION_HINT
        )


def load_render_settings() -> RenderSettings:
    """Load and validate the ``render`` namespace from the NoneBot config."""
    return get_plugin_config(RenderPluginConfig).render


__all__ = [
    "LEGACY_CONFIG_KEYS",
    "CacheSettings",
    "FilehostSettings",
    "LocalAccessSettings",
    "ObservabilitySettings",
    "RenderPluginConfig",
    "RenderSettings",
    "ResourceSettings",
    "TemplateSettings",
    "assert_no_legacy_render_keys",
    "detect_legacy_render_keys",
    "load_render_settings",
]
