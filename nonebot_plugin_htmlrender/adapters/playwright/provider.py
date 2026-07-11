"""Playwright engine provider: settings, availability, and composition."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from playwright.async_api import Error as PlaywrightError

from nonebot_plugin_htmlrender.adapters._lease import (
    LeasedBackendLifecycle,
    LeasedPreparedHtmlExecutor,
)
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PLAYWRIGHT_CAPABILITIES,
    PlaywrightCapabilities,
)
from nonebot_plugin_htmlrender.backend.playwright._page import open_page_context
from nonebot_plugin_htmlrender.backend.playwright.config import (
    PlaywrightConfig,
    register_playwright_config_provider,
)
from nonebot_plugin_htmlrender.backend.playwright.models import (
    ContentConfig,
    PageConfig,
    RenderConfig,
    ViewportConfig,
    _build_screenshot_config,
)
from nonebot_plugin_htmlrender.backend.playwright.operations import (
    render_prepared_html,
)
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
)
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
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy
from nonebot_plugin_htmlrender.resources.resolve import ResourceResolveError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from nonebot_plugin_htmlrender.backend.base import RenderSession
    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )

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
    except AssetMaterializationError as error:
        raise ResourceResolutionError(str(error)) from error
    except ResourceResolveError as error:
        raise ResourceResolutionError(str(error)) from error
    except PlaywrightError as error:
        raise runtime_error(f"Playwright {operation} failed: {error}") from error
    except Exception as error:
        raise runtime_error(f"Playwright {operation} failed: {error}") from error


def _strict_assets(policy: ResourcePolicy | None) -> bool | None:
    """Map the neutral per-call policy onto the browser asset pipeline."""
    if policy is None or policy is ResourcePolicy.STRICT:
        return True
    if policy is ResourcePolicy.AUTO:
        return False
    return None


async def _rasterize(
    session: RenderSession,
    prepared: PreparedHtml,
    options: RasterOptions,
    resource_policy: ResourcePolicy | None,
) -> bytes:
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
        session=session,
        strict_assets=_strict_assets(resource_policy),
        telemetry_op="playwright.html_render.rasterize_html",
    )


async def _probe(session: RenderSession) -> None:
    async with open_page_context(session=session):
        return


def _uses_filehost(config: PlaywrightConfig) -> bool:
    if config.resource_resolve_mode == ResourceResolveMode.OFF:
        return False
    return (
        config.remote_local_resource_policy == RemoteLocalResourcePolicy.FILEHOST
        or config.local_local_resource_policy == LocalLocalResourcePolicy.FILEHOST
    )


@final
class PlaywrightProvider:
    """First-party provider for the Playwright browser engine."""

    id: EngineId = "playwright"

    def parse_settings(self, raw: Mapping[str, object]) -> object:
        return PlaywrightConfig.model_validate(dict(raw))

    def availability(self, settings: object) -> ProviderAvailability:
        config = self._narrow(settings)
        from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
            is_playwright_backend_available,
        )

        result = is_playwright_backend_available(config)
        return ProviderAvailability(available=result.available, reason=result.reason)

    def bootstrap_requirements(
        self,
        settings: object,
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

    def compose(
        self,
        settings: object,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        config = self._narrow(settings)
        # The browser runtime modules still read module-level configuration;
        # route those reads to the composed settings until the physical
        # migration absorbs them into this adapter.
        register_playwright_config_provider(lambda: config)

        from nonebot_plugin_htmlrender.backend.playwright.render import (  # noqa: PLC0415
            PlaywrightBackend,
        )

        lifecycle = LeasedBackendLifecycle(
            backend=PlaywrightBackend(),
            observer=dependencies.operation_observer,
            translate=_translate,
            observation_attributes=_OBSERVATION_ATTRIBUTES,
            probe=_probe,
        )
        executor = LeasedPreparedHtmlExecutor(
            lifecycle=lifecycle,
            rasterize=_rasterize,
            translate=_translate,
            observer=dependencies.operation_observer,
            # playwright operations already emit the render span themselves.
            operation=None,
            observation_attributes=_OBSERVATION_ATTRIBUTES,
        )
        capabilities = CapabilityCatalog().with_capability(
            PLAYWRIGHT_CAPABILITIES,
            PlaywrightCapabilities(lifecycle),
        )
        return EngineBindings(
            lifecycle=lifecycle,
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
