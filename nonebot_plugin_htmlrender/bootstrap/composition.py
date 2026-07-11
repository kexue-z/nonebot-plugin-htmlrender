"""Process-level object graph composed from ``RenderSettings``.

This is the only place that resolves providers, selects observers, and
installs the process-level service seams. Business paths receive their
dependencies through constructors; nothing here is consulted at render time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.application import Application, build_application
from nonebot_plugin_htmlrender.providers.discovery import resolve_provider
from nonebot_plugin_htmlrender.providers.sdk import (
    EngineBindings,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering.errors import ProviderUnavailable
from nonebot_plugin_htmlrender.rendering.observers import (
    NoopCacheObserver,
    NoopOperationObserver,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceCacheSettings,
    ResourceConfig,
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
    from collections.abc import Sequence

    from nonebot_plugin_htmlrender.providers.sdk import (
        EngineProvider,
        PluginRequirement,
    )
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver

    from .settings import RenderSettings


@final
class _IdleLifecycle:
    """Lifecycle for compositions without a configured engine."""

    async def startup(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@final
class _UnavailableLifecycle:
    """Lifecycle that surfaces the provider availability failure."""

    def __init__(self, provider_id: str, reason: str) -> None:
        self._provider_id = provider_id
        self._reason = reason

    def _raise(self) -> ProviderUnavailable:
        return ProviderUnavailable(
            f"Provider `{self._provider_id}` is unavailable: {self._reason}"
        )

    async def startup(self) -> None:
        raise self._raise()

    async def probe(self) -> None:
        raise self._raise()

    async def aclose(self) -> None:
        return None


@final
class _UnavailableExecutor:
    """Executor that surfaces the provider availability failure."""

    def __init__(self, provider_id: str, reason: str) -> None:
        self._provider_id = provider_id
        self._reason = reason

    async def execute(
        self,
        prepared: object,
        options: object,
        *,
        resource_policy: object | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        del prepared, options, resource_policy, timeout_seconds
        raise ProviderUnavailable(
            f"Provider `{self._provider_id}` is unavailable: {self._reason}"
        )


@dataclass(frozen=True)
class ComposedRuntime:
    """Everything the NoneBot host needs after composition."""

    settings: RenderSettings
    provider: EngineProvider | None
    provider_settings: object | None
    plugin_requirements: tuple[PluginRequirement, ...]

    def build_application(self) -> Application:
        return _build_application_for(self)


def select_observers(
    settings: RenderSettings,
) -> tuple[OperationObserver, CacheObserver]:
    """Telemetry observers when any integration is on; no-ops otherwise."""
    observability = settings.observability
    if observability.sentry or observability.prometheus:
        return TelemetryOperationObserver(), TelemetryCacheObserver()
    return NoopOperationObserver(), NoopCacheObserver()


def build_core_resource_config(settings: RenderSettings) -> ResourceConfig:
    """Core-owned security and resource policy baseline."""
    local_access = settings.resources.local_access
    return ResourceConfig(
        filehost_allow_any_path=local_access.allow_any_path,
        filehost_allowed_paths=tuple(local_access.allowed_paths),
    )


def _resource_cache_settings(settings: RenderSettings) -> ResourceCacheSettings:
    return ResourceCacheSettings(
        max_entries=settings.resources.cache.max_entries,
        max_bytes=settings.resources.cache.max_bytes,
        revalidate_seconds=settings.resources.cache.revalidate_seconds,
        template_environment_max_entries=(
            settings.resources.templates.environment_cache_max_entries
        ),
    )


def prepare_runtime(
    settings: RenderSettings,
    *,
    explicit_providers: Sequence[EngineProvider] = (),
) -> ComposedRuntime:
    """Resolve the provider, parse its settings, and install process seams.

    Kept deliberately light: no engine runtime is created here, so it is safe
    to run at plugin import time even for ``startup: off`` deployments.
    """
    _, cache_observer = select_observers(settings)
    register_cache_observer_provider(lambda: cache_observer)
    cache_settings = _resource_cache_settings(settings)
    register_resource_cache_settings_provider(lambda: cache_settings)

    core_resource_config = build_core_resource_config(settings)
    if settings.provider is None:
        register_resource_config_provider(lambda: core_resource_config)
        return ComposedRuntime(
            settings=settings,
            provider=None,
            provider_settings=None,
            plugin_requirements=(),
        )

    provider = resolve_provider(settings.provider, explicit=explicit_providers)
    provider_settings = provider.parse_settings(settings.provider_config)
    resource_config = provider.resource_configuration(
        provider_settings,
        core_resource_config,
    )
    register_resource_config_provider(lambda: resource_config)
    return ComposedRuntime(
        settings=settings,
        provider=provider,
        provider_settings=provider_settings,
        plugin_requirements=provider.bootstrap_requirements(provider_settings),
    )


def _build_application_for(runtime: ComposedRuntime) -> Application:
    """Compose the engine and assemble the application (heavier path)."""
    operation_observer, cache_observer = select_observers(runtime.settings)
    if runtime.provider is None:
        return build_application(engine=EngineBindings(lifecycle=_IdleLifecycle()))

    provider = runtime.provider
    provider_settings = runtime.provider_settings
    if provider_settings is None:
        raise ProviderUnavailable(
            f"Provider `{provider.id}` has no parsed settings; "
            "composition was not prepared."
        )

    availability = provider.availability(provider_settings)
    if not availability.available:
        reason = availability.reason or "no availability reason was provided"
        engine = EngineBindings(
            lifecycle=_UnavailableLifecycle(provider.id, reason),
            prepared_html_executor=_UnavailableExecutor(provider.id, reason),
        )
        return build_application(engine=engine)

    dependencies = ProviderDependencies(
        operation_observer=operation_observer,
        cache_observer=cache_observer,
    )
    engine = provider.compose(provider_settings, dependencies)
    return build_application(engine=engine)


__all__ = [
    "ComposedRuntime",
    "build_core_resource_config",
    "prepare_runtime",
    "select_observers",
]
