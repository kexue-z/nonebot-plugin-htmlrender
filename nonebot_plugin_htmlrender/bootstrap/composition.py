"""NoneBot composition root for the complete process object graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, final

import anyio
from exceptiongroup import BaseExceptionGroup

from nonebot_plugin_htmlrender.adapters.observability import (
    TelemetryCacheObserver,
    TelemetryOperationObserver,
)
from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
    FilehostAssetPublisher,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.adapters.templates import JinjaTemplateCompiler
from nonebot_plugin_htmlrender.application import Application, build_application
from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer
from nonebot_plugin_htmlrender.providers.discovery import resolve_provider
from nonebot_plugin_htmlrender.providers.sdk import EngineBindings, ProviderDependencies
from nonebot_plugin_htmlrender.rendering.errors import ProviderUnavailable
from nonebot_plugin_htmlrender.rendering.observers import (
    NoopCacheObserver,
    NoopOperationObserver,
)
from nonebot_plugin_htmlrender.resources.config import (
    AssetPublisherSettings,
    ResourceCacheSettings,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from nonebot_plugin_htmlrender.providers.sdk import (
        EngineProvider,
        PluginRequirement,
    )
    from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
    from nonebot_plugin_htmlrender.rendering.ports import (
        ApplicationLifecycle,
        OperationObserver,
    )
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import AssetPublisher

    from .settings import RenderSettings


@final
class _IdleLifecycle:
    async def startup(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@final
class _UnavailableLifecycle:
    def __init__(self, provider_id: str, reason: str) -> None:
        self._provider_id = provider_id
        self._reason = reason

    def _error(self) -> ProviderUnavailable:
        return ProviderUnavailable(
            f"Provider `{self._provider_id}` is unavailable: {self._reason}"
        )

    async def startup(self) -> None:
        raise self._error()

    async def probe(self) -> None:
        raise self._error()

    async def aclose(self) -> None:
        return None


@final
class _UnavailableExecutor:
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
    ) -> RenderedImage:
        del prepared, options, resource_policy, timeout_seconds
        raise ProviderUnavailable(
            f"Provider `{self._provider_id}` is unavailable: {self._reason}"
        )


@final
class _ComposedLifecycle:
    def __init__(
        self,
        *,
        engine: ApplicationLifecycle,
        resources: ResourceService,
        templates: JinjaTemplateCompiler,
        publisher: AssetPublisher | None,
    ) -> None:
        self._engine = engine
        self._resources = resources
        self._templates = templates
        self._publisher = publisher

    @staticmethod
    async def _cleanup(
        *operations: Callable[[], Awaitable[None]],
    ) -> list[BaseException]:
        errors: list[BaseException] = []
        with anyio.CancelScope(shield=True):
            for operation in operations:
                try:
                    await operation()
                except BaseException as error:  # noqa: PERF203
                    errors.append(error)
        return errors

    @staticmethod
    def _raise_errors(message: str, errors: list[BaseException]) -> None:
        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise BaseExceptionGroup(message, errors)

    async def startup(self) -> None:
        try:
            if self._publisher is not None:
                await self._publisher.startup()
            await self._engine.startup()
        except BaseException as error:
            operations: list[Callable[[], Awaitable[None]]] = [
                self._templates.clear,
                self._resources.clear,
            ]
            if self._publisher is not None:
                operations.append(self._publisher.clear)
            cleanup_errors = await self._cleanup(*operations)
            self._raise_errors(
                "Application startup and rollback both failed.",
                [error, *cleanup_errors],
            )

    async def probe(self) -> None:
        await self._engine.probe()

    async def aclose(self) -> None:
        operations: list[Callable[[], Awaitable[None]]] = [
            self._engine.aclose,
            self._templates.clear,
            self._resources.clear,
        ]
        if self._publisher is not None:
            operations.extend((self._publisher.clear, self._publisher.aclose))
        errors = await self._cleanup(*operations)
        self._raise_errors("Application shutdown failed.", errors)


@dataclass(frozen=True)
class ComposedRuntime:
    settings: RenderSettings
    provider: EngineProvider[object] | None
    provider_settings: object | None
    plugin_requirements: tuple[PluginRequirement, ...]
    resource_strategy: ResourceStrategy

    def build_application(self) -> Application:
        return _build_application_for(self)

    @property
    def asset_publisher_settings(self) -> AssetPublisherSettings | None:
        if not _uses_publisher(self.resource_strategy):
            return None
        return _publisher_settings(self.settings)


def select_observers(
    settings: RenderSettings,
) -> tuple[OperationObserver, CacheObserver]:
    observability = settings.observability
    if observability.sentry or observability.prometheus:
        return (
            TelemetryOperationObserver(
                sentry=observability.sentry,
                prometheus=observability.prometheus,
            ),
            TelemetryCacheObserver(
                sentry=observability.sentry,
                prometheus=observability.prometheus,
            ),
        )
    return NoopOperationObserver(), NoopCacheObserver()


def _cache_settings(settings: RenderSettings) -> ResourceCacheSettings:
    cache = settings.resources.cache
    return ResourceCacheSettings(
        max_entries=cache.max_entries,
        max_bytes=cache.max_bytes,
        max_resource_bytes=cache.max_resource_bytes,
        revalidate_seconds=cache.revalidate_seconds,
        template_environment_max_entries=(
            settings.resources.templates.environment_cache_max_entries
        ),
    )


def _publisher_settings(settings: RenderSettings) -> AssetPublisherSettings:
    filehost = settings.resources.filehost
    return AssetPublisherSettings(
        cache_ttl_seconds=filehost.cache_ttl_seconds,
        request_header_name=filehost.request_header_name,
        request_header_value=filehost.request_header_value,
        request_header_salt=filehost.request_header_salt,
        prewarm_enabled=filehost.prewarm_enabled,
        prewarm_max_files=filehost.prewarm_max_files,
        prewarm_paths=tuple(filehost.prewarm_paths),
        prewarm_extensions=tuple(filehost.prewarm_extensions),
        max_resource_bytes=settings.resources.cache.max_resource_bytes,
    )


def _uses_publisher(strategy: ResourceStrategy) -> bool:
    policy = (
        strategy.remote_local_policy
        if strategy.is_remote
        else strategy.local_local_policy
    )
    return policy.value == "filehost"


def prepare_runtime(
    settings: RenderSettings,
    *,
    explicit_providers: Sequence[EngineProvider[object]] = (),
) -> ComposedRuntime:
    """Resolve and validate only the selected provider at import time."""
    if settings.provider is None:
        return ComposedRuntime(settings, None, None, (), ResourceStrategy())
    provider = resolve_provider(settings.provider, explicit=explicit_providers)
    provider_settings = provider.parse_settings(settings.provider_config)
    strategy = provider.resource_strategy(provider_settings)
    return ComposedRuntime(
        settings,
        provider,
        provider_settings,
        provider.bootstrap_requirements(provider_settings),
        strategy,
    )


def _build_application_for(runtime: ComposedRuntime) -> Application:
    operation_observer, cache_observer = select_observers(runtime.settings)
    cache_settings = _cache_settings(runtime.settings)
    worker = AnyioWorkerExecutor()
    reader = build_resource_reader(cache_settings, cache_observer, worker)
    local = runtime.settings.resources.local_access
    local_access = ConfiguredLocalAccessPolicy(
        allowed_roots=local.allowed_paths,
        allow_any=local.allow_any_path,
    )

    provider = runtime.provider
    provider_settings = runtime.provider_settings
    strategy = runtime.resource_strategy
    publisher: AssetPublisher | None = None
    if _uses_publisher(strategy):
        publisher = FilehostAssetPublisher(
            settings=_publisher_settings(runtime.settings),
            observer=cache_observer,
            worker=worker,
            local_access=local_access,
        )
    resources = ResourceService(
        reader=reader,
        local_access=local_access,
        strategy=strategy,
        publisher=publisher,
    )
    templates = JinjaTemplateCompiler(
        max_entries=cache_settings.template_environment_max_entries,
        observer=cache_observer,
        worker=worker,
        local_access=local_access,
    )
    preparer = DefaultHtmlPreparer(
        resources=resources,
        templates=templates,
        worker=worker,
    )

    if provider is None:
        engine = EngineBindings(
            lifecycle=_IdleLifecycle(),
        )
    else:
        if provider_settings is None:
            raise ProviderUnavailable(
                f"Provider `{provider.id}` has no parsed settings; composition was not prepared."
            )
        availability = provider.availability(provider_settings)
        if not availability.available:
            reason = availability.reason or "no availability reason was provided"
            engine = EngineBindings(
                lifecycle=_UnavailableLifecycle(provider.id, reason),
                prepared_html_executor=_UnavailableExecutor(provider.id, reason),
            )
        else:
            engine = provider.compose(
                provider_settings,
                ProviderDependencies(
                    operation_observer=operation_observer,
                    cache_observer=cache_observer,
                    worker_executor=worker,
                    resource_reader=reader,
                    local_access_policy=local_access,
                    resource_service=resources,
                    asset_publisher=publisher,
                ),
            )
    lifecycle = _ComposedLifecycle(
        engine=engine.lifecycle,
        resources=resources,
        templates=templates,
        publisher=publisher,
    )
    return build_application(
        engine=replace(engine, lifecycle=lifecycle),
        preparer=preparer,
        resources=resources,
    )


__all__ = ["ComposedRuntime", "prepare_runtime", "select_observers"]
