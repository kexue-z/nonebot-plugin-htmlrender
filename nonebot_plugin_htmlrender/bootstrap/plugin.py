"""NoneBot host integration: config load, import-time requires, lifecycle."""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from typing import TYPE_CHECKING

import nonebot
from nonebot import require
from nonebot.log import logger

from nonebot_plugin_htmlrender.api._default import (
    set_default_application,
    set_default_application_factory,
)
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    RenderStartupMode,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.resources.config import get_resource_config

from .composition import prepare_runtime
from .settings import assert_no_legacy_render_keys, load_render_settings

if TYPE_CHECKING:
    from .composition import ComposedRuntime
    from .settings import RenderSettings


def _require_optional_plugin(*, plugin_name: str, enabled: bool) -> None:
    """Eagerly ``require`` an optional plugin during plugin import.

    Import-time loading is required because these plugins register their own
    ``@driver.on_startup`` hooks (e.g. Prometheus mounts ``/metrics`` there);
    a lazy ``require`` at first render happens after the driver startup phase
    and the hook would never fire.
    """
    if not enabled:
        return
    if find_spec(plugin_name) is None:
        logger.opt(colors=True).warning(
            "Optional plugin <c>{plugin_name}</c> is enabled but not installed; "
            "skipping import bootstrap.",
            plugin_name=plugin_name,
        )
        return
    try:
        require(plugin_name)
    except Exception as error:
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


def patch_filehost_request_headers_validator() -> None:
    """修补 filehost 请求头验证器以兼容 pydantic。"""
    try:
        # TODO: Open an upstream issue for nonebot-plugin-filehost to replace
        # __get_validators__ with __get_pydantic_core_schema__.
        filehost_models = import_module("nonebot_plugin_filehost.models")
        request_headers = getattr(filehost_models, "RequestHeaders", None)
        request_scope_info = getattr(filehost_models, "RequestScopeInfo", None)
        if request_headers is None or request_scope_info is None:
            return
        if bool(getattr(request_headers, "__htmlrender_validator_patched__", False)):
            return

        raw_validate = request_headers.__dict__.get("validate")
        if not isinstance(raw_validate, classmethod):
            return

        validate_func = raw_validate.__func__

        def _compat_validate(cls, value, *args, **kwargs):  # type: ignore[no-untyped-def]
            """兼容性验证包装器。"""
            del args, kwargs
            return validate_func(cls, value)

        request_headers.validate = classmethod(_compat_validate)
        request_headers.__htmlrender_validator_patched__ = True
        model_rebuild = getattr(request_scope_info, "model_rebuild", None)
        if callable(model_rebuild):
            model_rebuild(force=True)
        logger.opt(colors=True).info(
            "Patched <c>nonebot_plugin_filehost</c> websocket scope validator "
            "for pydantic compatibility."
        )
    except Exception as e:
        logger.opt(colors=True).warning(
            "Failed to patch <c>nonebot_plugin_filehost</c> validator "
            "compatibility: <r>{e}</r>",
            e=e,
        )


def _filehost_resolution_configured() -> bool:
    """Whether the composed resource policy routes local assets to filehost."""
    config = get_resource_config()
    if config.resource_resolve_mode == ResourceResolveMode.OFF:
        return False
    return (
        config.remote_local_resource_policy == RemoteLocalResourcePolicy.FILEHOST
        or config.local_local_resource_policy == LocalLocalResourcePolicy.FILEHOST
    )


def _bootstrap_filehost_on_import() -> None:
    if not _filehost_resolution_configured():
        return
    filehost_module = import_module("nonebot_plugin_htmlrender.resources.filehost")
    if not filehost_module.ensure_filehost_plugin_loaded(reason="plugin_import"):
        return
    filehost_module.ensure_filehost_request_guard_installed(reason="plugin_import")


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
        _require_optional_plugin(plugin_name=requirement.plugin_name, enabled=True)
    _require_optional_plugin(
        plugin_name="nonebot_plugin_sentry",
        enabled=settings.observability.sentry,
    )
    _require_optional_plugin(
        plugin_name="nonebot_plugin_prometheus",
        enabled=settings.observability.prometheus,
    )
    _bootstrap_filehost_on_import()

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
        if _filehost_resolution_configured():
            filehost_module = import_module(
                "nonebot_plugin_htmlrender.resources.filehost"
            )
            await filehost_module.ensure_filehost_runtime_ready(reason="plugin_startup")
        application = get_default_application()
        await application.startup()
        if settings.startup == RenderStartupMode.PROBE:
            await application.probe()
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
    "patch_filehost_request_headers_validator",
    "run_shutdown",
    "run_startup",
]
