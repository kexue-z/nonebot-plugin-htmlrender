"""Takumi engine provider: settings, availability, and composition."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.adapters._lease import (
    LeasedBackendLifecycle,
    LeasedPreparedHtmlExecutor,
)
from nonebot_plugin_htmlrender.adapters.takumi.capabilities import (
    TAKUMI_CAPABILITIES,
    TakumiCapabilities,
)
from nonebot_plugin_htmlrender.backend.base import RenderRuntime, RenderSession
from nonebot_plugin_htmlrender.backend.takumi.config import TakumiConfig
from nonebot_plugin_htmlrender.backend.takumi.errors import (
    TakumiBackendError,
    TakumiInputError,
    TakumiResourceError,
    TakumiRuntimeError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.backend.takumi.operations import (
    rasterize_html as takumi_rasterize_html,
)
from nonebot_plugin_htmlrender.backend.takumi.runtime import (
    create_runtime_state,
    require_runtime_state,
)
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_html
from nonebot_plugin_htmlrender.providers.sdk import (
    EngineBindings,
    EngineId,
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog
from nonebot_plugin_htmlrender.rendering.errors import (
    InvalidRenderRequest,
    ProviderExecutionError,
    RenderingError,
    ResourceResolutionError,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import observe_operation

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Mapping

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.providers.sdk import PluginRequirement
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy
    from nonebot_plugin_htmlrender.resources.config import ResourceConfig
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver

_OBSERVATION_ATTRIBUTES: dict[str, str] = {"render.backend": "takumi"}
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


async def _noop_close() -> None:
    return None


@final
class _TakumiRuntimeBackend:
    """Legacy-shaped backend running against injected settings and observers."""

    backend: RenderBackend = RenderBackend.TAKUMI
    capabilities = frozenset()

    def __init__(
        self,
        *,
        config: TakumiConfig,
        operation_observer: OperationObserver,
        cache_observer: CacheObserver,
    ) -> None:
        self._config = config
        self._operation_observer = operation_observer
        self._cache_observer = cache_observer

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return ()

    async def create_runtime(self) -> RenderRuntime:
        with observe_operation(
            self._operation_observer,
            "takumi.open_runtime",
            _OBSERVATION_ATTRIBUTES,
        ):
            state = await create_runtime_state(
                self._config,
                cache_observer=self._cache_observer,
            )

        observer = self._operation_observer

        async def _aclose() -> None:
            with observe_operation(
                observer,
                "takumi.close_runtime",
                _OBSERVATION_ATTRIBUTES,
            ):
                await state.aclose()

        return RenderRuntime(
            backend=self.backend,
            handle=state,
            _aclose=_aclose,
        )

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: object,
    ) -> RenderSession:
        del kwargs
        state = require_runtime_state(runtime.handle)
        return RenderSession(runtime=runtime, handle=state, _aclose=_noop_close)

    def is_alive(self, session: RenderSession) -> bool:
        if session.handle is not session.runtime.handle:
            return False
        try:
            require_runtime_state(session.handle)
        except TakumiRuntimeError:
            return False
        return True


async def _rasterize(
    session: RenderSession,
    prepared: PreparedHtml,
    options: RasterOptions,
    resource_policy: ResourcePolicy | None,
) -> bytes:
    # Takumi materializes documents strictly regardless of the per-call policy.
    del resource_policy
    state = require_runtime_state(session.handle)
    return await takumi_rasterize_html(state, prepared, options)


async def _probe(session: RenderSession) -> None:
    state = require_runtime_state(session.handle)
    await takumi_rasterize_html(
        state,
        prepare_html(_PROBE_HTML),
        RasterOptions(width=8, height=8, device_pixel_ratio=1.0),
    )


@final
class TakumiProvider:
    """First-party provider for the Takumi native renderer."""

    id: EngineId = "takumi"

    def parse_settings(self, raw: Mapping[str, object]) -> object:
        return TakumiConfig.model_validate(dict(raw))

    def availability(self, settings: object) -> ProviderAvailability:
        self._narrow(settings)
        from nonebot_plugin_htmlrender.backend.takumi.render import (  # noqa: PLC0415
            is_takumi_backend_available,
        )

        result = is_takumi_backend_available()
        return ProviderAvailability(available=result.available, reason=result.reason)

    def bootstrap_requirements(
        self,
        settings: object,
    ) -> tuple[PluginRequirement, ...]:
        self._narrow(settings)
        return ()

    def resource_configuration(
        self,
        settings: object,
        base: ResourceConfig,
    ) -> ResourceConfig:
        self._narrow(settings)
        return base

    def compose(
        self,
        settings: object,
        dependencies: ProviderDependencies,
    ) -> EngineBindings:
        config = self._narrow(settings)
        backend = _TakumiRuntimeBackend(
            config=config,
            operation_observer=dependencies.operation_observer,
            cache_observer=dependencies.cache_observer,
        )
        lifecycle = LeasedBackendLifecycle(
            backend=backend,
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
            operation="takumi.rasterize_html",
            observation_attributes=_OBSERVATION_ATTRIBUTES,
        )
        capabilities = CapabilityCatalog().with_capability(
            TAKUMI_CAPABILITIES,
            TakumiCapabilities(lifecycle),
        )
        return EngineBindings(
            lifecycle=lifecycle,
            prepared_html_executor=executor,
            provider_capabilities=capabilities,
            description="Takumi native HTML renderer",
            observation_attributes=_OBSERVATION_ATTRIBUTES,
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
