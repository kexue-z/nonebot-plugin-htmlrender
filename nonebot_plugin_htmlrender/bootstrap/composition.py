"""NoneBot composition root for the complete process object graph."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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
    ConfiguredRemoteAccessPolicy,
    FilehostAssetPublisher,
    RemoteTransportExecutor,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.adapters.templates import JinjaTemplateCompiler
from nonebot_plugin_htmlrender.application import Application, build_application
from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer
from nonebot_plugin_htmlrender.providers.discovery import resolve_provider
from nonebot_plugin_htmlrender.providers.sdk import EngineBindings, ProviderDependencies
from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
from nonebot_plugin_htmlrender.rendering.budget import HtmlRenderBudget
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderLifecycleError,
    ProviderUnavailable,
)
from nonebot_plugin_htmlrender.rendering.observers import (
    NoopCacheObserver,
    NoopOperationObserver,
)
from nonebot_plugin_htmlrender.resources._traversal import ResourceTraversalBudget
from nonebot_plugin_htmlrender.resources.config import (
    AssetPublisherSettings,
    LocalLocalResourcePolicy,
    RemoteAccessSettings,
    RemoteLocalResourcePolicy,
    ResourceCacheSettings,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.service import ResourceService

from .graphics import build_graphics_capabilities

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.providers.sdk import (
        EngineProvider,
        PluginRequirement,
    )
    from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
    from nonebot_plugin_htmlrender.rendering.ports import (
        ApplicationLifecycle,
        OperationObserver,
    )
    from nonebot_plugin_htmlrender.resources.models import ResourceRef
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
class _ProviderResourceFacade:
    """Expose only the policy-bound resource operations promised by the SDK."""

    def __init__(self, delegate: ResourceService) -> None:
        self._delegate = delegate

    @property
    def strategy(self) -> ResourceStrategy:
        return self._delegate.strategy

    def authorize_local(self, path: Path) -> Path:
        return self._delegate.authorize_local(path)

    async def read_bytes(
        self,
        reference: str | Path | ResourceRef,
        *,
        refresh: bool = False,
    ) -> bytes:
        return await self._delegate.read_bytes(reference, refresh=refresh)


@final
class _ComposedLifecycle:
    """Startup transaction with reverse-order rollback and poisoning.

    ``startup`` records each completed step and, on failure, resets only the
    steps that completed, in reverse order. It stays retryable as long as
    that rollback fully succeeds; if any rollback step fails the composition
    is poisoned and further ``startup`` raises. ``aclose`` is best-effort over
    partial and poisoned state and aggregates every teardown error.
    """

    def __init__(
        self,
        *,
        engine: ApplicationLifecycle,
        resources: ResourceService,
        templates: JinjaTemplateCompiler,
        publisher: AssetPublisher | None,
        remote_transport: RemoteTransportExecutor,
    ) -> None:
        self._engine = engine
        self._resources = resources
        self._templates = templates
        self._publisher = publisher
        self._remote_transport = remote_transport
        self._poisoned = False

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
        if self._poisoned:
            raise ProviderLifecycleError(
                "Application composition is poisoned by a failed rollback; "
                "build a new composition before starting again."
            )
        # (do, undo) ordered by dependency; only completed steps are rolled
        # back, in reverse.  The engine is failure-atomic, so a raising
        # engine.startup leaves nothing of its own to undo.
        steps: list[tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]]
        steps = []
        if self._publisher is not None:
            steps.append((self._publisher.startup, self._publisher.clear))
        steps.append((self._engine.startup, self._engine.aclose))

        completed_undo: list[Callable[[], Awaitable[None]]] = []
        try:
            for do, undo in steps:
                await do()
                completed_undo.append(undo)
        except BaseException as error:
            rollback_errors = await self._cleanup(
                *reversed(completed_undo),
                self._templates.clear,
                self._resources.clear,
            )
            if rollback_errors:
                self._poisoned = True
                self._raise_errors(
                    "Application startup failed and rollback did not fully "
                    "succeed; composition is poisoned.",
                    [error, *rollback_errors],
                )
            raise

    async def probe(self) -> None:
        await self._engine.probe()

    async def aclose(self) -> None:
        operations: list[Callable[[], Awaitable[None]]] = [
            self._engine.aclose,
            self._templates.clear,
            self._resources.clear,
            self._remote_transport.aclose,
        ]
        if self._publisher is not None:
            operations.extend((self._publisher.clear, self._publisher.aclose))
        errors = await self._cleanup(*operations)
        self._raise_errors("Application shutdown failed.", errors)


@final
class ComposedRuntime:
    """Reusable composition plan backed by immutable configuration snapshots."""

    __slots__ = (
        "_plugin_requirements",
        "_provider",
        "_provider_settings",
        "_resource_strategy",
        "_settings",
    )

    def __init__(
        self,
        settings: RenderSettings,
        provider: EngineProvider[object] | None,
        provider_settings: object | None,
        plugin_requirements: tuple[PluginRequirement, ...],
        resource_strategy: ResourceStrategy,
    ) -> None:
        self._settings = settings.model_copy(deep=True)
        self._provider = provider
        self._provider_settings = deepcopy(provider_settings)
        self._plugin_requirements = tuple(plugin_requirements)
        self._resource_strategy = resource_strategy

    @property
    def settings(self) -> RenderSettings:
        """Return a detached view of the settings captured by this plan."""
        return self._settings.model_copy(deep=True)

    @property
    def provider(self) -> EngineProvider[object] | None:
        return self._provider

    @property
    def plugin_requirements(self) -> tuple[PluginRequirement, ...]:
        return self._plugin_requirements

    @property
    def resource_strategy(self) -> ResourceStrategy:
        return self._resource_strategy

    def _inputs_for_build(self) -> tuple[RenderSettings, object | None]:
        """Create isolated mutable inputs for one application composition."""
        return self._settings.model_copy(deep=True), deepcopy(self._provider_settings)

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
        template_environment_cache_size=(
            settings.resources.templates.environment_compiled_cache_size
        ),
    )


def _remote_access_settings(settings: RenderSettings) -> RemoteAccessSettings:
    remote = settings.resources.remote_access
    return RemoteAccessSettings(
        allow_private_networks=remote.allow_private_networks,
        allow_hosts=tuple(remote.allow_hosts),
        deny_hosts=tuple(remote.deny_hosts),
        max_redirects=remote.max_redirects,
        request_timeout_seconds=remote.request_timeout_seconds,
        max_concurrent_fetches=remote.max_concurrent_fetches,
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
        public_base_url=filehost.public_base_url,
        max_entries=filehost.max_entries,
        max_bytes=filehost.max_bytes,
    )


def _uses_publisher(strategy: ResourceStrategy) -> bool:
    if strategy.is_remote:
        return strategy.remote_local_policy is RemoteLocalResourcePolicy.FILEHOST
    return strategy.local_local_policy is LocalLocalResourcePolicy.FILEHOST


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
    if (
        _uses_publisher(strategy)
        and settings.resources.filehost.public_base_url is None
    ):
        # The hosted asset URL is deployment configuration; failing here is
        # deliberate so a misconfigured filehost transport never reaches the
        # first publish.
        raise ProviderUnavailable(
            "The selected resource strategy uses the filehost transport; "
            "set `render.resources.filehost.public_base_url` to the "
            "externally reachable hosted asset base URL."
        )
    return ComposedRuntime(
        settings,
        provider,
        provider_settings,
        provider.bootstrap_requirements(provider_settings),
        strategy,
    )


def _build_application_for(runtime: ComposedRuntime) -> Application:
    settings, provider_settings = runtime._inputs_for_build()
    operation_observer, cache_observer = select_observers(settings)
    cache_settings = _cache_settings(settings)
    worker = AnyioWorkerExecutor()
    operation_admission = OperationAdmissionGate()
    graphics_capabilities = build_graphics_capabilities(
        settings.graphics,
        worker=worker,
        observer=operation_observer,
        operation_admission=operation_admission,
    )
    remote_settings = _remote_access_settings(settings)
    remote_access = ConfiguredRemoteAccessPolicy(remote_settings)
    remote_transport = RemoteTransportExecutor(
        max_concurrent_fetches=remote_settings.max_concurrent_fetches
    )
    reader = build_resource_reader(
        cache_settings,
        cache_observer,
        worker,
        remote_access=remote_access,
        remote_transport=remote_transport,
        remote_timeout_seconds=remote_settings.request_timeout_seconds,
    )
    local = settings.resources.local_access
    local_access = ConfiguredLocalAccessPolicy(
        allowed_roots=local.allowed_paths,
        allow_any=local.allow_any_path,
    )

    provider = runtime.provider
    strategy = runtime.resource_strategy
    publisher: AssetPublisher | None = None
    if _uses_publisher(strategy):
        publisher = FilehostAssetPublisher(
            settings=_publisher_settings(settings),
            observer=cache_observer,
            worker=worker,
            local_access=local_access,
        )
    resources = ResourceService(
        reader=reader,
        local_access=local_access,
        strategy=strategy,
        publisher=publisher,
        traversal_budget=ResourceTraversalBudget(
            max_nodes=settings.resources.traversal.max_nodes,
            max_depth=settings.resources.traversal.max_depth,
            max_concurrency=settings.resources.traversal.max_concurrency,
        ),
    )
    provider_resources = _ProviderResourceFacade(resources)
    templates = JinjaTemplateCompiler(
        max_entries=cache_settings.template_environment_max_entries,
        observer=cache_observer,
        worker=worker,
        local_access=local_access,
        cache_size=cache_settings.template_environment_cache_size,
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
                    resources=provider_resources,
                    asset_publisher=publisher,
                ),
            )
    lifecycle = _ComposedLifecycle(
        engine=engine.lifecycle,
        resources=resources,
        templates=templates,
        publisher=publisher,
        remote_transport=remote_transport,
    )
    return build_application(
        engine=replace(engine, lifecycle=lifecycle),
        preparer=preparer,
        resources=resources,
        operation_admission=operation_admission,
        extensions=graphics_capabilities,
        html_render_budget=HtmlRenderBudget(
            max_source_bytes=settings.html.max_source_bytes,
            max_pixels=settings.html.max_pixels,
            max_output_bytes=settings.html.max_output_bytes,
            max_device_pixel_ratio=settings.html.max_device_pixel_ratio,
            max_auto_height=settings.html.max_auto_height,
            max_concurrency=settings.html.max_concurrency,
        ),
    )


__all__ = ["ComposedRuntime", "prepare_runtime"]
