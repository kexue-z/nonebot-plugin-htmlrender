from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nonebot_plugin_htmlrender.bootstrap.settings import (
    RenderPluginConfig,
    RenderSettings,
    assert_no_legacy_render_keys,
    detect_legacy_render_keys,
)
from nonebot_plugin_htmlrender.consts import RenderStartupMode


def test_render_settings_defaults() -> None:
    settings = RenderSettings()

    assert settings.provider is None
    assert settings.startup is RenderStartupMode.OFF
    assert settings.provider_config == {}
    assert settings.resources.cache.max_entries == 256
    assert settings.resources.cache.max_bytes == 64 * 1024 * 1024
    assert settings.resources.templates.environment_cache_max_entries == 64
    assert settings.resources.local_access.allow_any_path is False
    assert settings.resources.local_access.allowed_paths == []
    assert settings.observability.sentry is False
    assert settings.observability.prometheus is False


def test_render_settings_nested_parse() -> None:
    config = RenderPluginConfig.model_validate(
        {
            "render": {
                "provider": "takumi",
                "startup": "probe",
                "provider_config": {"max_concurrency": 2},
                "resources": {
                    "cache": {"max_entries": 8},
                    "local_access": {"allowed_paths": "assets"},
                },
                "observability": {"prometheus": True},
            }
        }
    )
    settings = config.render

    assert settings.provider == "takumi"
    assert settings.startup is RenderStartupMode.PROBE
    assert settings.provider_config == {"max_concurrency": 2}
    assert settings.resources.cache.max_entries == 8
    assert settings.resources.local_access.allowed_paths == [Path("assets")]
    assert settings.observability.prometheus is True


def test_legacy_key_detection() -> None:
    dirty = SimpleNamespace(render_backend="playwright", render_playwright={})
    clean = SimpleNamespace(render={"provider": None})

    assert detect_legacy_render_keys(dirty) == (
        "render_backend",
        "render_playwright",
    )
    assert detect_legacy_render_keys(clean) == ()

    with pytest.raises(RuntimeError, match="render_backend"):
        assert_no_legacy_render_keys(dirty)
    assert_no_legacy_render_keys(clean)
