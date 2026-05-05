from __future__ import annotations

from importlib.util import find_spec
import sys
from typing import TYPE_CHECKING

from nonebot import require
from nonebot.log import logger

from .common import get_config_value

if TYPE_CHECKING:
    from prometheus_client import Counter, Histogram

_PROM_COUNTER_NAME = "nonebot_htmlrender_operations_total"
_PROM_HISTOGRAM_NAME = "nonebot_htmlrender_duration_seconds"


class _PrometheusState:
    """缓存 Prometheus 集成的检查结果与指标实例。

    用于避免在每次记录指标时重复加载 ``nonebot_plugin_prometheus`` 模块，
    并在初始化失败后跳过后续的尝试。
    """

    def __init__(self) -> None:
        self.checked = False
        self.plugin: object | None = None
        self.counter: Counter | None = None
        self.histogram: Histogram | None = None


_state = _PrometheusState()


def is_prometheus_enabled() -> bool:
    """判断 Prometheus 集成是否启用。

    Returns:
        当配置中未显式设置为 ``False`` 时返回 ``True``。
    """
    enabled = get_config_value("prometheus_enable")
    return enabled is not False


def ensure_prometheus_plugin_loaded(*, reason: str) -> bool:
    """确保 ``nonebot_plugin_prometheus`` 已被加载并可用。

    第一次调用时尝试通过 NoneBot 的 ``require`` 机制加载插件，并将结果缓存；
    后续调用直接返回缓存结果。

    Args:
        reason: 触发加载的原因，仅用于日志输出。

    Returns:
        插件可用时返回 ``True``。
    """
    if _state.checked:
        return _state.plugin is not None

    _state.checked = True
    if find_spec("nonebot_plugin_prometheus") is None:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Prometheus plugin not installed, skip bootstrap ({reason}).",
            reason=reason,
        )
        return False

    try:
        require("nonebot_plugin_prometheus")
    except Exception as e:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus bootstrap failed ({reason}): <r>{error}</r>.",
            reason=reason,
            error=e,
        )
        return False

    _state.plugin = sys.modules.get("nonebot_plugin_prometheus")
    if _state.plugin is None:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus bootstrap incomplete ({reason}): `nonebot_plugin_prometheus` module not found after require.",
            reason=reason,
        )
        return False

    logger.opt(colors=True).debug(
        "<d>[htmlrender.telemetry]</d> Prometheus bootstrap ready ({reason}).",
        reason=reason,
    )
    return True


def load_prometheus() -> tuple[Counter, Histogram] | None:
    """加载并返回渲染相关的 Prometheus 计数器与直方图。

    Returns:
        ``(Counter, Histogram)`` 二元组；当 Prometheus 未启用、插件不可用
        或指标初始化失败时返回 ``None``。
    """
    if _state.counter is not None and _state.histogram is not None:
        return _state.counter, _state.histogram

    if not is_prometheus_enabled():
        return None

    if not ensure_prometheus_plugin_loaded(reason="runtime"):
        return None

    prometheus = _state.plugin or sys.modules.get("nonebot_plugin_prometheus")
    if prometheus is None:
        return None

    counter_cls = getattr(prometheus, "Counter", None)
    histogram_cls = getattr(prometheus, "Histogram", None)
    if counter_cls is None or histogram_cls is None:
        return None

    try:
        _state.counter = counter_cls(
            _PROM_COUNTER_NAME,
            "Total render operations.",
            ["op", "backend", "status"],
        )
        _state.histogram = histogram_cls(
            _PROM_HISTOGRAM_NAME,
            "Render operation duration in seconds.",
            ["op", "backend", "status"],
        )
    except Exception as exc:
        logger.debug(f"Failed to initialize Prometheus metrics: {exc}")
        _state.counter = None
        _state.histogram = None
        return None

    if _state.counter is None or _state.histogram is None:
        return None
    return _state.counter, _state.histogram


def record_metrics(
    op: str,
    backend: str,
    status: str,
    duration: float,
    trace_id: str | None,
) -> None:
    """记录一次渲染操作的 Prometheus 指标。

    若 Prometheus 集成未启用或不可用则静默返回；当提供 ``trace_id`` 时优先
    携带 exemplar 上报，遇到不支持 exemplar 的旧版本会自动回退为普通上报。

    Args:
        op: 操作名称，例如 ``render_html``。
        backend: 后端标识。
        status: 操作结果状态，例如 ``success``、``error``。
        duration: 操作耗时，单位为秒。
        trace_id: 关联的追踪 ID，用于 exemplar；可为 ``None``。
    """
    if not is_prometheus_enabled():
        return

    metrics = load_prometheus()
    if metrics is None:
        return

    counter, histogram = metrics
    labels = {"op": op, "backend": backend, "status": status}
    counter_metric = counter.labels(**labels)
    histogram_metric = histogram.labels(**labels)

    if trace_id:
        try:
            counter_metric.inc(1, exemplar={"trace_id": trace_id})
            counter_recorded = True
        except TypeError:
            counter_metric.inc()
            counter_recorded = True
        except Exception:
            counter_recorded = False
        else:
            counter_recorded = True
        try:
            histogram_metric.observe(duration, exemplar={"trace_id": trace_id})
            histogram_recorded = True
        except TypeError:
            histogram_recorded = False
        except Exception:
            histogram_recorded = False
        else:
            histogram_recorded = True
    else:
        counter_recorded = False
        histogram_recorded = False

    if not counter_recorded:
        counter_metric.inc()
    if not histogram_recorded:
        histogram_metric.observe(duration)
