"""NoneBot host integration: config load, import-time requires, lifecycle."""

from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING

from exceptiongroup import ExceptionGroup
import nonebot
from nonebot import require
from nonebot.log import logger

from nonebot_plugin_htmlrender.adapters.resources import (
    install_hosted_asset_store,
)
from nonebot_plugin_htmlrender.api._default import (
    set_default_application,
    set_default_application_factory,
)
from nonebot_plugin_htmlrender.rendering.errors import ProviderUnavailable

from .composition import prepare_runtime
from .settings import (
    RenderStartupMode,
    assert_no_legacy_render_keys,
    load_render_settings,
)

if TYPE_CHECKING:
    from .composition import ComposedRuntime
    from .settings import RenderSettings


def _require_optional_plugin(
    *,
    plugin_name: str,
    enabled: bool,
    required: bool = False,
) -> None:
    """Eagerly ``require`` an optional plugin during plugin import.

    Import-time loading is required because these plugins register their own
    ``@driver.on_startup`` hooks (e.g. Prometheus mounts ``/metrics`` there);
    a lazy ``require`` at first render happens after the driver startup phase
    and the hook would never fire.
    """
    if not enabled:
        return
    if find_spec(plugin_name) is None:
        if required:
            raise ProviderUnavailable(
                f"Required NoneBot plugin `{plugin_name}` is not installed."
            )
        logger.opt(colors=True).warning(
            "Optional plugin <c>{plugin_name}</c> is enabled but not installed; "
            "skipping import bootstrap.",
            plugin_name=plugin_name,
        )
        return
    try:
        require(plugin_name)
    except Exception as error:
        if required:
            raise ProviderUnavailable(
                f"Required NoneBot plugin `{plugin_name}` could not be loaded.",
                source=error,
            ) from error
        logger.opt(colors=True).warning(
            "Failed to bootstrap optional plugin <c>{plugin_name}</c> on import: "
            "<r>{error}</r>.",
            plugin_name=plugin_name,
            error=error,
        )
        return
    logger.opt(colors=True).debug(
        "Optional plugin <c>{plugin_name}</c> bootstrapped on import.",
        plugin_name=plugin_name,
    )


def initialize_plugin() -> RenderSettings:
    """Compose the process object graph and register lifecycle hooks.

    Runs at plugin import time. The engine itself is composed lazily on first
    default-application access so that ``startup: off`` deployments never pay
    engine import costs up front.
    """
    driver = nonebot.get_driver()
    assert_no_legacy_render_keys(driver.config)
    settings = load_render_settings()

    runtime = prepare_runtime(settings)

    for requirement in runtime.plugin_requirements:
        _require_optional_plugin(
            plugin_name=requirement.plugin_name,
            enabled=True,
            required=True,
        )
    _require_optional_plugin(
        plugin_name="nonebot_plugin_sentry",
        enabled=settings.observability.sentry,
    )
    _require_optional_plugin(
        plugin_name="nonebot_plugin_prometheus",
        enabled=settings.observability.prometheus,
    )
    publisher_settings = runtime.asset_publisher_settings
    if publisher_settings is not None:
        install_hosted_asset_store(publisher_settings)
    set_default_application(None)
    set_default_application_factory(runtime.build_application)
    _register_lifecycle_hooks(driver, runtime)
    return settings


def _register_lifecycle_hooks(driver: object, runtime: ComposedRuntime) -> None:
    on_startup = getattr(driver, "on_startup", None)
    on_shutdown = getattr(driver, "on_shutdown", None)
    if not callable(on_startup) or not callable(on_shutdown):
        logger.warning(
            "Driver does not expose startup/shutdown hooks; "
            "render runtime lifecycle is caller-managed."
        )
        return

    async def _startup() -> None:
        await run_startup(runtime)

    async def _shutdown() -> None:
        await run_shutdown()

    on_startup(_startup)
    on_shutdown(_shutdown)


async def run_startup(runtime: ComposedRuntime) -> None:
    """Apply the configured startup mode to the default application."""
    settings = runtime.settings
    logger.info("HTMLRender starting...")
    if settings.provider is None:
        logger.info("No render provider selected; startup skipped.")
        return
    if settings.startup == RenderStartupMode.OFF:
        logger.info("Render startup skipped by configuration.")
        return

    from nonebot_plugin_htmlrender.api._default import (  # noqa: PLC0415
        get_default_application,
    )

    try:
        application = get_default_application()
        await application.startup()
        if settings.startup == RenderStartupMode.PROBE:
            try:
                await application.probe()
            except Exception as probe_error:
                # A failed readiness probe must not leave a warmed runtime
                # behind after NoneBot aborts startup. A cleanup failure must
                # not mask the probe failure, so both are aggregated.
                try:
                    await application.aclose()
                except Exception as close_error:
                    raise ExceptionGroup(
                        "Render probe failed and runtime cleanup also failed.",
                        [probe_error, close_error],
                    ) from probe_error
                raise
    except Exception as error:
        logger.exception("Failed to start render runtime.")
        raise RuntimeError("Render runtime startup failed.") from error

    logger.opt(colors=True).info(
        "HTMLRender started with provider <cyan>{provider}</cyan>.",
        provider=settings.provider,
    )


async def run_shutdown() -> None:
    """Close the default application when one was built."""
    from nonebot_plugin_htmlrender.api._default import (  # noqa: PLC0415
        peek_default_application,
    )

    logger.info("HTMLRender shutting down...")
    application = peek_default_application()
    if application is not None:
        await application.aclose()
    logger.info("HTMLRender shut down.")


__all__ = [
    "initialize_plugin",
    "run_shutdown",
    "run_startup",
]
