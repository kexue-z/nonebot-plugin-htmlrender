"""Playwright engine provider: settings, availability, and composition.

Browser modules are imported lazily so that loading the plugin with
``startup: off`` never pulls the Playwright package until the first render.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters._lease import (
    ExecutionLeaseProvider,
    PreparedHtmlLeaseExecutor,
)
from nonebot_plugin_htmlrender.adapters.playwright.config import PlaywrightConfig
from nonebot_plugin_htmlrender.consts import RemoteLocalResourcePolicy
from nonebot_plugin_htmlrender.providers.sdk import (
    EngineBindings,
    EngineId,
    PluginRequirement,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderExecutionError,
    RenderingError,
)
from nonebot_plugin_htmlrender.rendering.requests import (
    ResourcePolicy,
    effective_resource_resolve_mode,
)
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease
    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )
    from nonebot_plugin_htmlrender.resources.ports import AssetPublisher
    from nonebot_plugin_htmlrender.resources.service import ResourceService

_OBSERVATION_ATTRIBUTES: dict[str, str] = {"render.backend": "playwright"}


@contextmanager
def _translate(
    operation: str,
    runtime_error: type[RenderingError],
) -> Iterator[None]:
    """Translate native Playwright failures into the stable error model."""
    try:
        yield
    except RenderingError:
        raise
    except Exception as error:
        raise runtime_error(f"Playwright {operation} failed: {error}") from error


async def _rasterize(
    lease: PlaywrightLease,
    prepared: PreparedHtml,
    options: RasterOptions,
    resource_policy: ResourcePolicy | None,
    *,
    resources: ResourceService,
    asset_publisher: AssetPublisher | None,
) -> bytes:
    from nonebot_plugin_htmlrender.adapters.playwright.models import (  # noqa: PLC0415
        ContentConfig,
        PageConfig,
        RenderConfig,
        ViewportConfig,
        _build_screenshot_config,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.operations import (  # noqa: PLC0415
        render_prepared_html,
    )

    viewport_height = options.height if options.height is not None else 10
    render = RenderConfig(
        page=PageConfig(
            viewport=ViewportConfig(
                width=options.width,
                height=viewport_height,
            ),
        ),
        screenshot=_build_screenshot_config(
            options.format,
            quality=options.quality,
            device_scale_factor=options.device_pixel_ratio,
            screenshot_timeout=30_000,
            full_page=options.height is None,
            wait_before_screenshot=0,
        ),
    )
    return await render_prepared_html(
        prepared,
        content=ContentConfig(html=prepared.html),
        render=render,
        lease=lease,
        resources=resources,
        asset_publisher=asset_publisher,
        resolve_mode=effective_resource_resolve_mode(
            resource_policy,
            resources.strategy.resolve_mode,
        ),
        telemetry_op="playwright.html_render.rasterize_html",
    )


async def _probe(lease: PlaywrightLease) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
        open_page_context,
    )

    async with open_page_context(lease=lease):
        return


def _uses_filehost(config: PlaywrightConfig) -> bool:
    is_remote = bool(config.connect_ws.endpoint or config.connect_cdp.endpoint)
    policy = (
        config.remote_local_resource_policy
        if is_remote
        else config.local_local_resource_policy
    )
    return policy.value == RemoteLocalResourcePolicy.FILEHOST.value


@final
class PlaywrightProvider:
    """First-party provider for the Playwright browser engine."""

    id: EngineId = "playwright"

    def parse_settings(self, raw: Mapping[str, object]) -> PlaywrightConfig:
        return PlaywrightConfig.model_validate(dict(raw))

    def availability(self, settings: PlaywrightConfig) -> ProviderAvailability:
        config = self._narrow(settings)
        from nonebot_plugin_htmlrender.adapters.playwright.availability import (  # noqa: PLC0415
            playwright_availability,
        )

        return playwright_availability(config)

    def bootstrap_requirements(
        self,
        settings: PlaywrightConfig,
    ) -> tuple[PluginRequirement, ...]:
        config = self._narrow(settings)
        if _uses_filehost(config):
            return (
                PluginRequirement(
                    plugin_name="nonebot_plugin_filehost",
                    reason="filehost local-resource policy is enabled",
                ),
            )
        return ()

    def resource_strategy(self, settings: PlaywrightConfig) -> ResourceStrategy:
        config = self._narrow(settings)
        return ResourceStrategy(
            is_remote=bool(config.connect_ws.endpoint or config.connect_cdp.endpoint),
            resolve_mode=config.resource_resolve_mode,
            remote_local_policy=config.remote_local_resource_policy,
            local_local_policy=config.local_local_resource_policy,
        )

    def compose(
        self,
        settings: PlaywrightConfig,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        config = self._narrow(settings)

        from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (  # noqa: PLC0415
            PLAYWRIGHT_CAPABILITIES,
            PlaywrightCapabilities,
        )
        from nonebot_plugin_htmlrender.adapters.playwright.render import (  # noqa: PLC0415
            PlaywrightEngine,
        )

        engine = PlaywrightEngine(
            config,
            operation_observer=dependencies.operation_observer,
        )
        leases = ExecutionLeaseProvider(
            create=engine.create_lease,
            is_alive=engine.is_alive,
            close=engine.close_lease,
            observer=dependencies.operation_observer,
            translate=_translate,
            observation_attributes=_OBSERVATION_ATTRIBUTES,
            probe=_probe,
        )

        async def rasterize(
            lease: PlaywrightLease,
            prepared: PreparedHtml,
            options: RasterOptions,
            resource_policy: ResourcePolicy | None,
        ) -> bytes:
            return await _rasterize(
                lease,
                prepared,
                options,
                resource_policy,
                resources=dependencies.resource_service,
                asset_publisher=dependencies.asset_publisher,
            )

        executor = PreparedHtmlLeaseExecutor(
            leases=leases,
            rasterize=rasterize,
            translate=_translate,
            observer=dependencies.operation_observer,
            operation="playwright.html_render.rasterize_html",
            observation_attributes=_OBSERVATION_ATTRIBUTES,
        )
        capabilities = CapabilityCatalog().with_capability(
            PLAYWRIGHT_CAPABILITIES,
            PlaywrightCapabilities(leases, dependencies.operation_observer),
        )
        return EngineBindings(
            lifecycle=leases,
            prepared_html_executor=executor,
            provider_capabilities=capabilities,
            description="Playwright browser engine",
            observation_attributes=_OBSERVATION_ATTRIBUTES,
        )

    @staticmethod
    def _narrow(settings: object) -> PlaywrightConfig:
        if not isinstance(settings, PlaywrightConfig):
            raise ProviderExecutionError(
                "Playwright provider received settings that were not produced "
                "by parse_settings()."
            )
        return settings


PROVIDER = PlaywrightProvider()

__all__ = ["PROVIDER", "PlaywrightProvider"]
