from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.observability import (
    TelemetryCacheObserver,
    TelemetryOperationObserver,
)
from nonebot_plugin_htmlrender.bootstrap.composition import (
    prepare_runtime,
    select_observers,
)
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.consts import (
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
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
    ResourceAccessDenied,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )


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
    def __init__(
        self,
        *,
        available: bool = True,
        strategy: ResourceStrategy | None = None,
    ) -> None:
        self.id = "fake-engine"
        self.available = available
        self.strategy = strategy or ResourceStrategy(is_remote=True)
        self.parsed: list[Mapping[str, object]] = []
        self.dependencies: list[ProviderDependencies] = []

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

    def resource_strategy(self, settings: object) -> ResourceStrategy:
        del settings
        return self.strategy

    def compose(
        self,
        settings: object,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        del settings
        self.dependencies.append(dependencies)
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


def test_composition_owns_local_access_security(tmp_path: Path) -> None:
    settings = RenderSettings.model_validate(
        {
            "resources": {
                "local_access": {
                    "allowed_paths": [tmp_path],
                }
            }
        }
    )

    application = prepare_runtime(settings).build_application()

    allowed = tmp_path / "assets" / "logo.png"
    assert application.resources.authorize_local(allowed) == allowed.resolve()
    with pytest.raises(ResourceAccessDenied, match="outside allowed roots"):
        application.resources.authorize_local(tmp_path.parent / "outside.png")


def test_provider_free_runtime_builds_isolated_preparation_apps() -> None:
    settings = RenderSettings.model_validate(
        {"resources": {"cache": {"max_entries": 17}}}
    )

    runtime = prepare_runtime(settings)
    first = runtime.build_application()
    second = runtime.build_application()

    assert runtime.provider is None
    assert runtime.plugin_requirements == ()
    assert first.renderer.capabilities == frozenset({"render_template_html"})
    assert first.resources is not second.resources
    assert first.preparation is not second.preparation


async def test_available_provider_receives_explicit_dependencies_and_renders() -> None:
    strategy = ResourceStrategy(is_remote=True)
    provider = _FakeProvider(available=True, strategy=strategy)
    settings = RenderSettings.model_validate(
        {"provider": "fake-engine", "provider_config": {"answer": 42}}
    )

    runtime = prepare_runtime(settings, explicit_providers=[provider])
    application = runtime.build_application()

    assert provider.parsed == [{"answer": 42}]
    assert [item.plugin_name for item in runtime.plugin_requirements] == ["fake_plugin"]
    assert len(provider.dependencies) == 1
    dependencies = provider.dependencies[0]
    assert dependencies.resource_service is application.resources
    assert dependencies.resource_reader is not None
    assert dependencies.local_access_policy is not None
    assert dependencies.worker_executor is not None
    assert dependencies.asset_publisher is None
    assert application.resources.strategy is strategy

    artifact = await application.renderer.render_html(
        RenderHtmlRequest(html="<p>hi</p>")
    )
    assert bytes(artifact) == b"fake-image"


def test_filehost_strategy_injects_asset_publisher() -> None:
    provider = _FakeProvider(
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        )
    )
    settings = RenderSettings.model_validate({"provider": "fake-engine"})

    application = prepare_runtime(
        settings,
        explicit_providers=[provider],
    ).build_application()

    assert provider.dependencies[0].asset_publisher is not None
    assert provider.dependencies[0].resource_service is application.resources


def test_filehost_strategy_off_keeps_publisher_for_per_call_override() -> None:
    provider = _FakeProvider(
        strategy=ResourceStrategy(
            is_remote=True,
            resolve_mode=ResourceResolveMode.OFF,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        )
    )
    runtime = prepare_runtime(
        RenderSettings.model_validate({"provider": "fake-engine"}),
        explicit_providers=[provider],
    )

    application = runtime.build_application()

    assert runtime.asset_publisher_settings is not None
    assert provider.dependencies[0].asset_publisher is not None
    assert provider.dependencies[0].resource_service is application.resources


async def test_unavailable_provider_surfaces_reason() -> None:
    provider = _FakeProvider(available=False)
    settings = RenderSettings.model_validate({"provider": "fake-engine"})

    runtime = prepare_runtime(settings, explicit_providers=[provider])
    application = runtime.build_application()

    assert provider.dependencies == []
    with pytest.raises(ProviderUnavailable, match="engine missing"):
        await application.renderer.render_html(RenderHtmlRequest(html="<p>hi</p>"))
    with pytest.raises(ProviderUnavailable, match="engine missing"):
        await application.startup()
