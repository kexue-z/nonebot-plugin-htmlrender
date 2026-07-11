from collections.abc import Mapping
from pathlib import Path
from typing import cast

from nonebot import get_plugin_config
from nonebot.compat import model_validator
from nonebot.log import logger
import nonebot_plugin_localstore as store
from pydantic import BaseModel, Field

from nonebot_plugin_htmlrender.consts import RenderBackend, RenderStartupMode
from nonebot_plugin_htmlrender.resources.config import (
    ResourceCacheSettings,
    register_resource_cache_settings_provider,
)
from nonebot_plugin_htmlrender.resources.observation import (
    register_cache_observer_provider,
)
from nonebot_plugin_htmlrender.utils.telemetry import TelemetryCacheObserver

plugin_cache_dir: Path = store.get_plugin_cache_dir()
plugin_config_dir: Path = store.get_plugin_config_dir()
plugin_data_dir: Path = store.get_plugin_data_dir()


def _get(obj: object, name: str, default: object = None) -> object:
    """从对象或映射中安全获取属性值。

    Args:
        obj: 目标对象，可以是 :class:`Mapping` 或普通对象。
        name: 要获取的属性名。
        default: 属性不存在时返回的默认值。

    Returns:
        属性值，或 *default*。
    """
    if isinstance(obj, Mapping):
        return cast("Mapping[str, object]", obj).get(name, default)
    return getattr(obj, name, default)


class Config(BaseModel):
    """Core plugin configuration.

    Only plugin-level settings live here. Backend-specific settings are defined
    in each backend package and loaded on demand.
    """

    render_backend: RenderBackend | None = Field(default=None)
    render_storage_path: Path = Field(default=plugin_data_dir)
    render_cache_path: Path = Field(default=plugin_cache_dir)
    render_config_path: Path = Field(default=plugin_config_dir)
    render_startup_mode: RenderStartupMode = Field(default=RenderStartupMode.OFF)
    render_resource_cache_max_entries: int = Field(default=256, ge=0)
    render_resource_cache_max_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=0,
    )
    render_resource_cache_revalidate_seconds: float = Field(default=1.0, ge=0.0)
    render_template_environment_cache_max_entries: int = Field(default=64, ge=0)

    @model_validator(mode="before")
    @classmethod
    def validate_render_backend(cls, data: object) -> object:
        """验证渲染后端配置。"""
        if _get(data, "render_backend") is None:
            logger.info(
                "[htmlrender] render_backend is not set; runtime startup will be skipped."
            )
        return data


plugin_config = get_plugin_config(Config)


def _plugin_resource_cache_settings() -> ResourceCacheSettings:
    return ResourceCacheSettings(
        max_entries=plugin_config.render_resource_cache_max_entries,
        max_bytes=plugin_config.render_resource_cache_max_bytes,
        revalidate_seconds=plugin_config.render_resource_cache_revalidate_seconds,
        template_environment_max_entries=(
            plugin_config.render_template_environment_cache_max_entries
        ),
    )


register_resource_cache_settings_provider(_plugin_resource_cache_settings)
register_cache_observer_provider(TelemetryCacheObserver)
