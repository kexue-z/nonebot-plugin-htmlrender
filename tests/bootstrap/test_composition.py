from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.bootstrap.composition import (
    build_core_resource_config,
    prepare_runtime,
    select_observers,
)
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.providers.sdk import (
    EngineBindings,
    PluginRequirement,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering import (
    NoopOperationObserver,
    ProviderUnavailable,
    RenderHtmlRequest,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.config import (
    ResourceConfig,
    get_resource_cache_settings,
    get_resource_config,
    register_resource_cache_settings_provider,
    register_resource_config_provider,
)
from nonebot_plugin_htmlrender.resources.observation import (
    register_cache_observer_provider,
)
from nonebot_plugin_htmlrender.utils.telemetry import (
    TelemetryCacheObserver,
    TelemetryOperationObserver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )


@pytest.fixture(autouse=True)
def _restore_process_seams() -> Iterator[None]:
    previous_observer = register_cache_observer_provider(None)
    register_cache_observer_provider(previous_observer)
    previous_settings = register_resource_cache_settings_provider(None)
    register_resource_cache_settings_provider(previous_settings)
    previous_config = register_resource_config_provider(None)
    register_resource_config_provider(previous_config)
    yield
    register_cache_observer_provider(previous_observer)
    register_resource_cache_settings_provider(previous_settings)
    register_resource_config_provider(previous_config)


class _FakeLifecycle:
    async def startup(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _FakeExecutor:
    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: object | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        del prepared, options, resource_policy, timeout_seconds
        return b"fake-image"


class _FakeProvider:
    def __init__(self, *, available: bool = True) -> None:
        self.id = "fake-engine"
        self.available = available
        self.parsed: list[Mapping[str, object]] = []

    def parse_settings(self, raw: Mapping[str, object]) -> object:
        self.parsed.append(dict(raw))
        return {"parsed": dict(raw)}

    def availability(self, settings: object) -> ProviderAvailability:
        del settings
        if self.available:
            return ProviderAvailability(available=True)
        return ProviderAvailability(available=False, reason="engine missing")

    def bootstrap_requirements(
        self,
        settings: object,
    ) -> tuple[PluginRequirement, ...]:
        del settings
        return (PluginRequirement(plugin_name="fake_plugin", reason="testing"),)

    def resource_configuration(
        self,
        settings: object,
        base: ResourceConfig,
    ) -> ResourceConfig:
        del settings
        return replace(base, is_remote_mode=True)

    def compose(
        self,
        settings: object,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        del settings, dependencies
        return EngineBindings(
            lifecycle=_FakeLifecycle(),
            prepared_html_executor=_FakeExecutor(),
        )


def test_select_observers_follows_observability_flags() -> None:
    off = RenderSettings()
    on = RenderSettings.model_validate({"observability": {"prometheus": True}})

    operation_off, cache_off = select_observers(off)
    operation_on, cache_on = select_observers(on)

    assert isinstance(operation_off, NoopOperationObserver)
    assert isinstance(cache_off, NoopCacheObserver)
    assert isinstance(operation_on, TelemetryOperationObserver)
    assert isinstance(cache_on, TelemetryCacheObserver)


def test_core_resource_config_owns_local_access_security() -> None:
    settings = RenderSettings.model_validate(
        {
            "resources": {
                "local_access": {
                    "allow_any_path": True,
                    "allowed_paths": ["assets"],
                }
            }
        }
    )

    config = build_core_resource_config(settings)

    assert config.filehost_allow_any_path is True
    assert config.filehost_allowed_paths == (Path("assets"),)


def test_prepare_runtime_without_provider_builds_preparation_only_app() -> None:
    settings = RenderSettings.model_validate(
        {"resources": {"cache": {"max_entries": 17}}}
    )

    runtime = prepare_runtime(settings)

    assert runtime.provider is None
    assert runtime.plugin_requirements == ()
    assert get_resource_cache_settings().max_entries == 17
    application = runtime.build_application()
    assert application.renderer.capabilities == frozenset({"render_template_html"})


async def test_prepare_runtime_with_available_provider_composes_engine() -> None:
    provider = _FakeProvider(available=True)
    settings = RenderSettings.model_validate(
        {"provider": "fake-engine", "provider_config": {"answer": 42}}
    )

    runtime = prepare_runtime(settings, explicit_providers=[provider])

    assert provider.parsed == [{"answer": 42}]
    assert [item.plugin_name for item in runtime.plugin_requirements] == ["fake_plugin"]
    assert get_resource_config().is_remote_mode is True

    application = runtime.build_application()
    artifact = await application.renderer.render_html(
        RenderHtmlRequest(html="<p>hi</p>")
    )
    assert bytes(artifact) == b"fake-image"


async def test_prepare_runtime_with_unavailable_provider_surfaces_reason() -> None:
    provider = _FakeProvider(available=False)
    settings = RenderSettings.model_validate({"provider": "fake-engine"})

    runtime = prepare_runtime(settings, explicit_providers=[provider])
    application = runtime.build_application()

    with pytest.raises(ProviderUnavailable, match="engine missing"):
        await application.renderer.render_html(RenderHtmlRequest(html="<p>hi</p>"))
    with pytest.raises(ProviderUnavailable, match="engine missing"):
        await application.startup()
