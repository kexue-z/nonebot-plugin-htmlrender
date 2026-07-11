from __future__ import annotations

from importlib.util import find_spec
import sys
from typing import TYPE_CHECKING, Mapping, cast

from nonebot import require
from nonebot.log import logger

from .common import call_metric, get_config_value, set_span_attribute

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from typing import Any

_SENTRY_METRIC_DURATION = "nonebot.htmlrender.duration"
_SENTRY_METRIC_COUNT = "nonebot.htmlrender.count"
_SENTRY_FILEHOST_UPLOAD_BYTES = "nonebot.htmlrender.filehost.upload_bytes"
_SENTRY_FILEHOST_DEDUP_HITS = "nonebot.htmlrender.filehost.dedup_hits"
_SENTRY_FILEHOST_ACTIVE_MAPPINGS = "nonebot.htmlrender.filehost.active_url_mappings"
_SENTRY_FILEHOST_ACTIVE_LEASES = "nonebot.htmlrender.filehost.active_leases"
_SENTRY_FILEHOST_CLEANUP_CAPABLE = (
    "nonebot.htmlrender.filehost.physical_cleanup_capable"
)


class _SentryState:
    """缓存 Sentry SDK 实例与首次加载结果。"""

    def __init__(self) -> None:
        self.sdk: object | None = None
        self.checked = False


_state = _SentryState()


def is_sentry_enabled() -> bool:
    """判断 Sentry 集成是否启用。

    Returns:
        当配置中存在非空的 ``sentry_dsn`` 时返回 ``True``。
    """
    return bool(get_config_value("sentry_dsn"))


def is_sentry_tracing_enabled() -> bool:
    """判断 Sentry 性能追踪是否启用。

    Returns:
        Sentry 已启用且配置了任意采样配置项时返回 ``True``。
    """
    if not is_sentry_enabled():
        return False
    return (
        get_config_value("sentry_traces_sample_rate") is not None
        or get_config_value("sentry_traces_sampler") is not None
    )


def is_sentry_profiling_enabled() -> bool:
    """判断 Sentry 性能分析（profiling）是否启用。

    Returns:
        Sentry 已启用且配置了任意 profiling 采样项时返回 ``True``。
    """
    if not is_sentry_enabled():
        return False
    return (
        get_config_value("sentry_profiles_sample_rate") is not None
        or get_config_value("sentry_profiles_sampler") is not None
        or get_config_value("sentry_profile_session_sample_rate") is not None
    )


def ensure_sentry_plugin_loaded(*, reason: str) -> bool:
    """确保 ``nonebot_plugin_sentry`` 已被加载并可用。

    第一次调用时尝试加载，并将结果缓存供后续调用复用。

    Args:
        reason: 触发加载的原因，仅用于日志输出。

    Returns:
        SDK 可用时返回 ``True``。
    """
    try:
        if not is_sentry_enabled():
            return False
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot read Sentry configuration "
            "({reason}): <r>{error}</r>.",
            reason=reason,
            error=error,
        )
        return False

    if _state.checked:
        return _state.sdk is not None

    _state.checked = True
    try:
        installed = find_spec("nonebot_plugin_sentry") is not None
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot locate Sentry plugin "
            "({reason}): <r>{error}</r>.",
            reason=reason,
            error=error,
        )
        return False
    if not installed:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Sentry plugin not installed, skip bootstrap ({reason}).",
            reason=reason,
        )
        return False

    try:
        require("nonebot_plugin_sentry")
    except Exception as e:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry bootstrap failed ({reason}): <r>{error}</r>.",
            reason=reason,
            error=e,
        )
        return False

    _state.sdk = sys.modules.get("sentry_sdk")
    if _state.sdk is None:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry bootstrap incomplete ({reason}): `sentry_sdk` not found after require.",
            reason=reason,
        )
        return False

    logger.opt(colors=True).debug(
        "<d>[htmlrender.telemetry]</d> Sentry bootstrap ready ({reason}).",
        reason=reason,
    )
    return True


def load_sentry() -> object | None:
    """获取已加载的 Sentry SDK 模块。

    Returns:
        Sentry SDK 模块；若插件未启用或加载失败则返回 ``None``。
    """
    try:
        if not is_sentry_enabled():
            return None
        if not ensure_sentry_plugin_loaded(reason="runtime"):
            return None
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry provider initialization "
            "failed: <r>{error}</r>.",
            error=error,
        )
        return None
    return _state.sdk


def record_metrics(op: str, backend: str, status: str, duration: float) -> None:
    """向 Sentry metrics 上报一次渲染操作。

    自动选择可用的 ``count`` / ``increment`` / ``incr`` 与 ``distribution`` 接口；当 SDK
    未启用、不可用或缺少 metrics 接口时静默返回。

    Args:
        op: 操作名称，例如 ``render_html``。
        backend: 后端标识。
        status: 操作结果状态。
        duration: 操作耗时，单位为秒。
    """
    try:
        if not is_sentry_enabled():
            return

        sentry = load_sentry()
        if sentry is None:
            return

        metrics = getattr(sentry, "metrics", None)
        if metrics is None:
            return

        tags = {"op": op, "backend": backend, "status": status}
        count = (
            getattr(metrics, "count", None)
            or getattr(metrics, "increment", None)
            or getattr(metrics, "incr", None)
        )
        distribution = getattr(metrics, "distribution", None)

        if callable(count):
            logger.opt(colors=True).debug(
                "<d>[htmlrender.telemetry]</d> Report Sentry counter metric: "
                "<c>{metric}</c> op=<y>{op}</y> backend=<y>{backend}</y> status=<y>{status}</y>.",
                metric=_SENTRY_METRIC_COUNT,
                op=op,
                backend=backend,
                status=status,
            )
            try:
                call_metric(count, _SENTRY_METRIC_COUNT, 1, unit=None, tags=tags)
            except Exception as error:
                logger.opt(colors=True).warning(
                    "<d>[htmlrender.telemetry]</d> Sentry counter export "
                    "failed: <r>{error}</r>.",
                    error=error,
                )
        if callable(distribution):
            logger.opt(colors=True).debug(
                "<d>[htmlrender.telemetry]</d> Report Sentry duration metric: "
                "<c>{metric}</c> duration=<y>{duration:.6f}</y>s op=<y>{op}</y> backend=<y>{backend}</y> status=<y>{status}</y>.",
                metric=_SENTRY_METRIC_DURATION,
                duration=duration,
                op=op,
                backend=backend,
                status=status,
            )
            try:
                call_metric(
                    distribution,
                    _SENTRY_METRIC_DURATION,
                    duration,
                    unit="second",
                    tags=tags,
                )
            except Exception as error:
                logger.opt(colors=True).warning(
                    "<d>[htmlrender.telemetry]</d> Sentry duration export "
                    "failed: <r>{error}</r>.",
                    error=error,
                )
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry metric provider failed: "
            "<r>{error}</r>.",
            error=error,
        )


def start_trace(
    op: str,
    name: str,
    attrs: Mapping[str, str] | None,
) -> AbstractContextManager[Any] | None:
    """创建一个 Sentry 事务/跨度对象。

    使用 Sentry 2.x 的 context-manager API。有活动 span 时创建子 span，
    否则创建根 transaction。

    Args:
        op: 事务/跨度的操作名。
        name: 事务/跨度的名称。
        attrs: 附加属性映射，可为 ``None``。

    Returns:
        Sentry 返回的事务/跨度对象；当 SDK 不可用或追踪未启用时返回 ``None``。
    """
    try:
        tracing_enabled = is_sentry_tracing_enabled()
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot read Sentry tracing "
            "configuration: <r>{error}</r>.",
            error=error,
        )
        return None

    if not tracing_enabled:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Skip Sentry trace creation: "
            "tracing_enabled=<c>{tracing_enabled}</c>. Use console debug fallback.",
            tracing_enabled=tracing_enabled,
        )
        return None

    sentry = load_sentry()
    if sentry is None:
        return None

    try:
        get_current_span = getattr(sentry, "get_current_span", None)
        parent = get_current_span() if callable(get_current_span) else None
        start_span = getattr(sentry, "start_span", None)
        start_transaction = getattr(sentry, "start_transaction", None)
        start_callable = (
            start_span
            if parent is not None and callable(start_span)
            else start_transaction
        )
        if not callable(start_callable):
            start_callable = start_span
        if not callable(start_callable):
            logger.opt(colors=True).debug(
                "<d>[htmlrender.telemetry]</d> Skip Sentry trace creation: "
                "start callable not available."
            )
            return None

        kwargs: dict[str, object] = {"op": op, "name": name}
        if start_callable is start_transaction:
            kwargs["source"] = "task"
        trace_obj = start_callable(**kwargs)
        if trace_obj is None:
            return None
        for key, value in (attrs or {}).items():
            set_span_attribute(trace_obj, key, value)
        return cast("AbstractContextManager[Any]", trace_obj)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry trace creation failed: "
            "<r>{error}</r>.",
            error=error,
        )
        return None


def record_filehost_cache_metrics(
    event: str,
    value: int,
    active_mappings: int,
    active_leases: int,
    physical_cleanup_capable: int,
) -> None:
    """Record low-cardinality filehost counters and gauges through Sentry 2.x."""

    try:
        if not is_sentry_enabled():
            return
        sentry = load_sentry()
        metrics = getattr(sentry, "metrics", None) if sentry is not None else None
        if metrics is None:
            return
        count = (
            getattr(metrics, "count", None)
            or getattr(metrics, "increment", None)
            or getattr(metrics, "incr", None)
        )
        gauge = getattr(metrics, "gauge", None)
        tags = {"component": "filehost"}
        if callable(count) and event == "upload":
            call_metric(
                count,
                _SENTRY_FILEHOST_UPLOAD_BYTES,
                value,
                unit="byte",
                tags=tags,
            )
        elif callable(count) and event == "dedup":
            call_metric(
                count,
                _SENTRY_FILEHOST_DEDUP_HITS,
                value,
                unit=None,
                tags=tags,
            )
        if callable(gauge):
            call_metric(
                gauge,
                _SENTRY_FILEHOST_ACTIVE_MAPPINGS,
                active_mappings,
                unit=None,
                tags=tags,
            )
            call_metric(
                gauge,
                _SENTRY_FILEHOST_ACTIVE_LEASES,
                active_leases,
                unit=None,
                tags=tags,
            )
            call_metric(
                gauge,
                _SENTRY_FILEHOST_CLEANUP_CAPABLE,
                physical_cleanup_capable,
                unit=None,
                tags=tags,
            )
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry filehost metric export failed: "
            "<r>{error}</r>.",
            error=error,
        )
