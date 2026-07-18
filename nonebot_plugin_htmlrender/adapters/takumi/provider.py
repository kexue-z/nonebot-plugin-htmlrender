"""Takumi engine provider: settings, availability, and composition."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters._lease import (
    ExecutionLeaseProvider,
    PreparedHtmlLeaseExecutor,
)
from nonebot_plugin_htmlrender.adapters.takumi.capabilities import (
    TakumiCapabilityAdapter,
)
from nonebot_plugin_htmlrender.adapters.takumi.config import TakumiConfig
from nonebot_plugin_htmlrender.adapters.takumi.errors import (
    TakumiBackendError,
    TakumiInputError,
    TakumiResourceError,
    TakumiRuntimeError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.adapters.takumi.operations import (
    rasterize_html as takumi_rasterize_html,
)
from nonebot_plugin_htmlrender.adapters.takumi.runtime import (
    create_runtime_state,
    require_runtime_state,
)
from nonebot_plugin_htmlrender.capabilities import TAKUMI_CAPABILITIES
from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_html
from nonebot_plugin_htmlrender.providers.sdk import (
    TAKUMI_PROVIDER_ID,
    EngineBindings,
    EngineId,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
from nonebot_plugin_htmlrender.rendering.errors import (
    InvalidRenderRequest,
    ProviderExecutionError,
    RenderingError,
    ResourceResolutionError,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import observe_operation
from nonebot_plugin_htmlrender.rendering.requests import (
    effective_resource_resolve_mode,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.providers.sdk import PluginRequirement
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources

    from .runtime import TakumiRuntimeState

_OBSERVATION_ATTRIBUTES: dict[str, str] = {"render.backend": TAKUMI_PROVIDER_ID}
_PROBE_HTML = '<div style="width:1px;height:1px"></div>'


@contextmanager
def _translate(
    operation: str,
    runtime_error: type[RenderingError],
) -> Iterator[None]:
    """Translate native Takumi failures into the stable error model."""
    try:
        yield
    except RenderingError:
        raise
    except TakumiUnsupportedError as error:
        raise UnsupportedRequirement(str(error)) from error
    except TakumiInputError as error:
        raise InvalidRenderRequest(str(error)) from error
    except TakumiResourceError as error:
        raise ResourceResolutionError(str(error)) from error
    except TakumiBackendError as error:
        raise runtime_error(f"Takumi {operation} failed: {error}") from error
    except Exception as error:
        raise runtime_error(f"Takumi {operation} failed: {error}") from error


@final
class TakumiEngine:
    """Own one native Takumi runtime using injected settings and observers."""

    def __init__(
        self,
        *,
        config: TakumiConfig,
        operation_observer: OperationObserver,
        cache_observer: CacheObserver,
        resources: ProviderResources,
    ) -> None:
        self._config = config
        self._operation_observer = operation_observer
        self._cache_observer = cache_observer
        self._resources = resources

    async def create_lease(self) -> TakumiRuntimeState:
        with observe_operation(
            self._operation_observer,
            "takumi.open_runtime",
            _OBSERVATION_ATTRIBUTES,
        ):
            return await create_runtime_state(
                self._config,
                resources=self._resources,
                cache_observer=self._cache_observer,
            )

    def is_alive(self, state: TakumiRuntimeState) -> bool:
        try:
            require_runtime_state(state)
        except TakumiRuntimeError:
            return False
        return True

    async def close_lease(self, state: TakumiRuntimeState) -> None:
        with observe_operation(
            self._operation_observer,
            "takumi.close_runtime",
            _OBSERVATION_ATTRIBUTES,
        ):
            await state.aclose()


async def _rasterize(
    state: TakumiRuntimeState,
    prepared: PreparedHtml,
    options: RasterOptions,
    resource_policy: ResourcePolicy | None,
    *,
    default_resolve_mode: ResourceResolveMode,
) -> RenderedImage:
    data = await takumi_rasterize_html(
        require_runtime_state(state),
        prepared,
        options,
        resolve_mode=effective_resource_resolve_mode(
            resource_policy,
            default_resolve_mode,
        ),
    )
    return RenderedImage.from_bytes(data, expected_format=options.format)


async def _probe(state: TakumiRuntimeState) -> None:
    state = require_runtime_state(state)
    await takumi_rasterize_html(
        state,
        prepare_html(_PROBE_HTML),
        RasterOptions(width=8, height=8, device_pixel_ratio=1.0),
    )


@final
class TakumiProvider:
    """First-party provider for the Takumi native renderer."""

    id: EngineId = TAKUMI_PROVIDER_ID

    def parse_settings(self, raw: Mapping[str, object]) -> TakumiConfig:
        return TakumiConfig.model_validate(dict(raw))

    def availability(self, settings: TakumiConfig) -> ProviderAvailability:
        self._narrow(settings)
        from nonebot_plugin_htmlrender.adapters.takumi.render import (  # noqa: PLC0415
            takumi_availability,
        )

        return takumi_availability()

    def bootstrap_requirements(
        self,
        settings: TakumiConfig,
    ) -> tuple[PluginRequirement, ...]:
        self._narrow(settings)
        return ()

    def resource_strategy(self, settings: TakumiConfig) -> ResourceStrategy:
        self._narrow(settings)
        return ResourceStrategy()

    def compose(
        self,
        settings: TakumiConfig,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        config = self._narrow(settings)
        engine = TakumiEngine(
            config=config,
            operation_observer=dependencies.operation_observer,
            cache_observer=dependencies.cache_observer,
            resources=dependencies.resources,
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
            state: TakumiRuntimeState,
            prepared: PreparedHtml,
            options: RasterOptions,
            resource_policy: ResourcePolicy | None,
        ) -> RenderedImage:
            return await _rasterize(
                state,
                prepared,
                options,
                resource_policy,
                default_resolve_mode=dependencies.resources.strategy.resolve_mode,
            )

        executor = PreparedHtmlLeaseExecutor(
            leases=leases,
            rasterize=rasterize,
            translate=_translate,
            observer=dependencies.operation_observer,
            operation="takumi.rasterize_html",
            observation_attributes=_OBSERVATION_ATTRIBUTES,
        )
        capabilities = CapabilityCatalog().with_capability(
            TAKUMI_CAPABILITIES,
            TakumiCapabilityAdapter(leases, dependencies.operation_observer),
        )
        return EngineBindings(
            lifecycle=leases,
            prepared_html_executor=executor,
            provider_capabilities=capabilities,
        )

    @staticmethod
    def _narrow(settings: object) -> TakumiConfig:
        if not isinstance(settings, TakumiConfig):
            raise ProviderExecutionError(
                "Takumi provider received settings that were not produced by "
                "parse_settings()."
            )
        return settings


PROVIDER = TakumiProvider()

__all__ = ["PROVIDER", "TakumiProvider"]
