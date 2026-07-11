"""Bootstrap helpers executed at plugin import time."""

from importlib import import_module
from importlib.util import find_spec

from nonebot import require
from nonebot.log import logger

from nonebot_plugin_htmlrender.config import plugin_config
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    RenderBackend,
    ResourceResolveMode,
)


def _enum_value(raw: object) -> str:
    """Return the string value for enum-like configuration entries."""
    return getattr(raw, "value", str(raw))


def _playwright_filehost_policy_enabled() -> bool:
    """Check whether Playwright config explicitly needs filehost bootstrap."""
    try:
        config_module = import_module(
            "nonebot_plugin_htmlrender.backend.playwright.config"
        )
        get_playwright_config = config_module.get_playwright_config
        cfg = get_playwright_config()
    except Exception as e:
        logger.warning(f"Skipping filehost import bootstrap: invalid config: {e}")
        return False

    if _enum_value(cfg.resource_resolve_mode) == ResourceResolveMode.OFF.value:
        return False

    return (
        _enum_value(cfg.remote_local_resource_policy)
        == RemoteLocalResourcePolicy.FILEHOST.value
        or _enum_value(cfg.local_local_resource_policy)
        == LocalLocalResourcePolicy.FILEHOST.value
    )


def _patch_filehost_request_headers_validator() -> None:
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
            "Patched <c>nonebot_plugin_filehost</c> websocket scope validator for pydantic compatibility."
        )
    except Exception as e:
        logger.opt(colors=True).warning(
            "Failed to patch <c>nonebot_plugin_filehost</c> validator compatibility: <r>{e}</r>",
            e=e,
        )


def _require_optional_plugin_on_import(
    *,
    plugin_name: str,
    integration_enabled: bool,
) -> None:
    """Eagerly ``require`` an optional telemetry plugin during plugin import.

    Import-time loading is required because these plugins register their own
    ``@driver.on_startup`` hooks (e.g. Prometheus mounts the ``/metrics`` route
    there); a lazy ``require`` at first render happens after the driver startup
    phase has already been consumed, so the hook would never fire. Loading is
    gated on this plugin's own configuration so an installed-but-unwanted
    integration is never force-loaded.
    """

    if not integration_enabled:
        return
    if find_spec(plugin_name) is None:
        logger.opt(colors=True).debug(
            "Optional plugin <d>{plugin_name}</d> enabled but not installed, "
            "skip import bootstrap.",
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


def _bootstrap_optional_plugins_on_import() -> None:
    """Load enabled telemetry plugins before the driver startup phase runs."""

    prometheus = import_module("nonebot_plugin_htmlrender.utils.telemetry.prometheus")
    sentry = import_module("nonebot_plugin_htmlrender.utils.telemetry.sentry")
    _require_optional_plugin_on_import(
        plugin_name="nonebot_plugin_prometheus",
        integration_enabled=prometheus.is_prometheus_enabled(),
    )
    _require_optional_plugin_on_import(
        plugin_name="nonebot_plugin_sentry",
        integration_enabled=sentry.is_sentry_enabled(),
    )


def _bootstrap_filehost_guard_on_import() -> None:
    """在导入时安装 filehost 请求守卫。"""

    if plugin_config.render_backend != RenderBackend.PLAYWRIGHT:
        return
    if not _playwright_filehost_policy_enabled():
        return

    filehost_module = import_module("nonebot_plugin_htmlrender.resources.filehost")
    ensure_filehost_plugin_loaded = filehost_module.ensure_filehost_plugin_loaded
    ensure_filehost_request_guard_installed = (
        filehost_module.ensure_filehost_request_guard_installed
    )

    if not ensure_filehost_plugin_loaded(reason="plugin_import"):
        return
    ensure_filehost_request_guard_installed(reason="plugin_import")
