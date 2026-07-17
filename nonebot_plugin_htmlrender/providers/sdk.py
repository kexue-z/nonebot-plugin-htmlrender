"""Provider SDK: the formal contract between the plugin and render engines.

A provider is loaded either from an explicit composition-root override or
from the ``nonebot_plugin_htmlrender.providers`` entry-point group. Settings
flow through the provider opaquely: the composition root calls
``parse_settings`` and hands the result straight back to ``availability``,
``bootstrap_requirements``, and ``compose``. Providers narrow the settings
object internally; this keeps entry-point loading fully typed without
generics over dynamically discovered classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, TypeAlias, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
    from nonebot_plugin_htmlrender.rendering.ports import (
        ApplicationLifecycle,
        OperationObserver,
        PreparedHtmlExecutor,
    )
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import (
        AssetPublisher,
        LocalAccessPolicy,
        ResourceReader,
        WorkerExecutor,
    )
    from nonebot_plugin_htmlrender.resources.service import ResourceService

from nonebot_plugin_htmlrender.resources.config import ResourceStrategy

EngineId: TypeAlias = str
SettingsT = TypeVar("SettingsT")

ENTRY_POINT_GROUP = "nonebot_plugin_htmlrender.providers"

RESERVED_PROVIDER_IDS: frozenset[EngineId] = frozenset(
    {"htmlkit", "playwright", "takumi"}
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "RESERVED_PROVIDER_IDS",
    "EngineBindings",
    "EngineId",
    "EngineProvider",
    "PluginRequirement",
    "ProviderAvailability",
    "ProviderDependencies",
    "ResourceStrategy",
]


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    """Whether a provider can run in the current environment."""

    available: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PluginRequirement:
    """A NoneBot plugin the bootstrap must ``require`` at import time."""

    plugin_name: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ProviderDependencies:
    """Services the composition root hands to ``EngineProvider.compose``.

    Providers never read global configuration or construct their own
    observers; everything they need arrives here.
    """

    operation_observer: OperationObserver
    cache_observer: CacheObserver
    worker_executor: WorkerExecutor
    resource_reader: ResourceReader
    local_access_policy: LocalAccessPolicy
    resource_service: ResourceService
    asset_publisher: AssetPublisher | None


@dataclass(frozen=True, slots=True)
class EngineBindings:
    """Immutable composition DTO produced by ``EngineProvider.compose``.

    Only the composition root consumes this; application code receives the
    contained lifecycle and executor through constructor injection.
    """

    lifecycle: ApplicationLifecycle
    prepared_html_executor: PreparedHtmlExecutor | None = None
    provider_capabilities: CapabilityCatalog | None = None
    description: str = ""
    observation_attributes: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class EngineProvider(Protocol[SettingsT]):
    """A render engine packaged for discovery and composition."""

    @property
    def id(self) -> EngineId: ...

    def parse_settings(self, raw: Mapping[str, object]) -> SettingsT: ...

    def availability(self, settings: SettingsT) -> ProviderAvailability: ...

    def bootstrap_requirements(
        self,
        settings: SettingsT,
    ) -> tuple[PluginRequirement, ...]: ...

    def resource_strategy(self, settings: SettingsT) -> ResourceStrategy: ...

    def compose(
        self,
        settings: SettingsT,
        dependencies: ProviderDependencies,
    ) -> EngineBindings: ...
