"""First-party provider composition for nonebot-plugin-htmlkit rc5."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.providers.sdk import (
    HTMLKIT_PROVIDER_ID,
    EngineBindings,
    EngineId,
    PluginRequirement,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering.errors import ProviderExecutionError
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy

from .availability import htmlkit_availability
from .config import HtmlkitConfig
from .executor import HtmlkitExecutor, HtmlkitLifecycle

if TYPE_CHECKING:
    from collections.abc import Mapping


@final
class HtmlkitProvider:
    """Experimental HTML engine backed by nonebot-plugin-htmlkit 0.1.0rc5."""

    id: EngineId = HTMLKIT_PROVIDER_ID

    def parse_settings(self, raw: Mapping[str, object]) -> HtmlkitConfig:
        return HtmlkitConfig.model_validate(dict(raw))

    def availability(self, settings: HtmlkitConfig) -> ProviderAvailability:
        self._narrow(settings)
        return htmlkit_availability()

    def bootstrap_requirements(
        self,
        settings: HtmlkitConfig,
    ) -> tuple[PluginRequirement, ...]:
        self._narrow(settings)
        return (
            PluginRequirement(
                plugin_name="nonebot_plugin_htmlkit",
                reason="HTMLKit provider selected",
            ),
        )

    def resource_strategy(self, settings: HtmlkitConfig) -> ResourceStrategy:
        config = self._narrow(settings)
        return ResourceStrategy(resolve_mode=config.resource_resolve_mode)

    def compose(
        self,
        settings: HtmlkitConfig,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        config = self._narrow(settings)
        executor = HtmlkitExecutor(
            config=config,
            resources=dependencies.resources,
            observer=dependencies.operation_observer,
        )
        return EngineBindings(
            lifecycle=HtmlkitLifecycle(executor),
            prepared_html_executor=executor,
        )

    @staticmethod
    def _narrow(settings: object) -> HtmlkitConfig:
        if not isinstance(settings, HtmlkitConfig):
            raise ProviderExecutionError(
                "HTMLKit provider received settings that were not produced by "
                "parse_settings()."
            )
        return settings


PROVIDER = HtmlkitProvider()

__all__ = ["PROVIDER", "HtmlkitProvider"]
