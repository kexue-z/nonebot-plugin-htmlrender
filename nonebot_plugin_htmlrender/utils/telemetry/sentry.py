from __future__ import annotations

from importlib.util import find_spec
import sys
from typing import Mapping

from nonebot import require
from nonebot.log import logger

from .common import call_metric, get_config_value, metric_params

_SENTRY_METRIC_DURATION = "nonebot.htmlrender.duration"
_SENTRY_METRIC_COUNT = "nonebot.htmlrender.count"


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
    if _state.checked:
        return _state.sdk is not None

    _state.checked = True
    if find_spec("nonebot_plugin_sentry") is None:
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
    ensure_sentry_plugin_loaded(reason="runtime")
    return _state.sdk


def record_metrics(op: str, backend: str, status: str, duration: float) -> None:
    """向 Sentry metrics 上报一次渲染操作。

    自动选择可用的 ``increment`` / ``incr`` 与 ``distribution`` 接口；当 SDK
    未启用、不可用或缺少 metrics 接口时静默返回。

    Args:
        op: 操作名称，例如 ``render_html``。
        backend: 后端标识。
        status: 操作结果状态。
        duration: 操作耗时，单位为秒。
    """
    if not is_sentry_enabled():
        return

    sentry = load_sentry()
    if sentry is None:
        return

    metrics = getattr(sentry, "metrics", None)
    if metrics is None:
        return

    tags = {"op": op, "backend": backend, "status": status}
    increment = getattr(metrics, "increment", None) or getattr(metrics, "incr", None)
    distribution = getattr(metrics, "distribution", None)

    if callable(increment):
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Report Sentry counter metric: "
            "<c>{metric}</c> op=<y>{op}</y> backend=<y>{backend}</y> status=<y>{status}</y>.",
            metric=_SENTRY_METRIC_COUNT,
            op=op,
            backend=backend,
            status=status,
        )
        call_metric(increment, _SENTRY_METRIC_COUNT, 1, unit=None, tags=tags)
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
        call_metric(
            distribution, _SENTRY_METRIC_DURATION, duration, unit="second", tags=tags
        )


def start_trace(
    op: str,
    name: str,
    attrs: Mapping[str, str] | None,
) -> object | None:
    """创建一个 Sentry 事务/跨度对象。

    根据 SDK 版本自动选择 ``start_transaction`` 或 ``start_span``，并按目标
    函数支持的参数填充 ``op``、``name``、``description``、``attributes``/``data`` 等字段。

    Args:
        op: 事务/跨度的操作名。
        name: 事务/跨度的名称。
        attrs: 附加属性映射，可为 ``None``。

    Returns:
        Sentry 返回的事务/跨度对象；当 SDK 不可用或追踪未启用时返回 ``None``。
    """
    sentry = load_sentry()
    tracing_enabled = is_sentry_tracing_enabled()
    if sentry is None or not tracing_enabled:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Skip Sentry trace creation: sdk_loaded=<c>{sdk_loaded}</c> tracing_enabled=<c>{tracing_enabled}</c>. Use console debug fallback.",
            sdk_loaded=sentry is not None,
            tracing_enabled=tracing_enabled,
        )
        return None

    start_transaction = getattr(sentry, "start_transaction", None)
    start = getattr(sentry, "start_span", None)
    start_callable = start_transaction or start
    if not callable(start_callable):
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Skip Sentry trace creation: start callable not available."
        )
        return None

    params = metric_params(start_callable)
    kwargs: dict[str, object] = {}
    if "op" in params:
        kwargs["op"] = op
    if "name" in params:
        kwargs["name"] = name
    elif "description" in params:
        kwargs["description"] = name
    if "source" in params:
        kwargs["source"] = "task"
    if attrs:
        if "attributes" in params:
            kwargs["attributes"] = dict(attrs)
        elif "data" in params:
            kwargs["data"] = dict(attrs)

    trace_obj = start_callable(**kwargs)
    return trace_obj if trace_obj is not None else None
