from __future__ import annotations

from importlib.util import find_spec
import sys
import threading
from typing import TYPE_CHECKING, Mapping, cast

from nonebot import require
from nonebot.log import logger

from .common import get_config_value

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

_PROM_COUNTER_NAME = "nonebot_htmlrender_operations_total"
_PROM_HISTOGRAM_NAME = "nonebot_htmlrender_duration_seconds"
_PROM_FILEHOST_UPLOAD_BYTES_NAME = "nonebot_htmlrender_filehost_upload_bytes"
_PROM_FILEHOST_DEDUP_HITS_NAME = "nonebot_htmlrender_filehost_dedup_hits"
_PROM_FILEHOST_ACTIVE_MAPPINGS_NAME = "nonebot_htmlrender_filehost_active_url_mappings"
_PROM_FILEHOST_ACTIVE_LEASES_NAME = "nonebot_htmlrender_filehost_active_leases"
_PROM_FILEHOST_CLEANUP_CAPABLE_NAME = (
    "nonebot_htmlrender_filehost_physical_cleanup_capable"
)
_PROM_CACHE_EVENTS_NAME = "nonebot_htmlrender_cache_events"
_PROM_CACHE_ENTRIES_NAME = "nonebot_htmlrender_cache_entries"
_PROM_CACHE_RESIDENT_BYTES_NAME = "nonebot_htmlrender_cache_resident_bytes"


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
        self.filehost_upload_bytes: Counter | None = None
        self.filehost_dedup_hits: Counter | None = None
        self.filehost_active_mappings: Gauge | None = None
        self.filehost_active_leases: Gauge | None = None
        self.filehost_cleanup_capable: Gauge | None = None
        self.cache_events: Counter | None = None
        self.cache_entries: Gauge | None = None
        self.cache_resident_bytes: Gauge | None = None


_state = _PrometheusState()
_state_lock = threading.RLock()


def is_prometheus_enabled() -> bool:
    """判断 Prometheus 集成是否启用。

    Returns:
        仅当配置显式设置为 ``True`` 时返回 ``True``；默认关闭。
    """
    return get_config_value("prometheus_enable") is True


def _ensure_prometheus_plugin_loaded(*, reason: str) -> bool:
    """确保 ``nonebot_plugin_prometheus`` 已被加载并可用。

    第一次调用时尝试通过 NoneBot 的 ``require`` 机制加载插件，并将结果缓存；
    后续调用直接返回缓存结果。

    Args:
        reason: 触发加载的原因，仅用于日志输出。

    Returns:
        插件可用时返回 ``True``。
    """
    try:
        if not is_prometheus_enabled():
            return False
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot read Prometheus configuration "
            "({reason}): <r>{error}</r>.",
            reason=reason,
            error=error,
        )
        return False

    if _state.checked:
        return _state.plugin is not None

    _state.checked = True
    try:
        installed = find_spec("nonebot_plugin_prometheus") is not None
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot locate Prometheus plugin "
            "({reason}): <r>{error}</r>.",
            reason=reason,
            error=error,
        )
        return False
    if not installed:
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


def ensure_prometheus_plugin_loaded(*, reason: str) -> bool:
    """Serialize optional-plugin discovery and bootstrap."""

    with _state_lock:
        return _ensure_prometheus_plugin_loaded(reason=reason)


def _load_prometheus() -> tuple[Counter, Histogram] | None:
    """加载并返回渲染相关的 Prometheus 计数器与直方图。

    Returns:
        ``(Counter, Histogram)`` 二元组；当 Prometheus 未启用、插件不可用
        或指标初始化失败时返回 ``None``。
    """
    try:
        if not is_prometheus_enabled():
            return None
        if _state.counter is not None and _state.histogram is not None:
            return _state.counter, _state.histogram
        if not ensure_prometheus_plugin_loaded(reason="runtime"):
            return None

        prometheus = _state.plugin or sys.modules.get("nonebot_plugin_prometheus")
        if prometheus is None:
            return None

        counter_cls = getattr(prometheus, "Counter", None)
        histogram_cls = getattr(prometheus, "Histogram", None)
        if counter_cls is None or histogram_cls is None:
            return None

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
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus provider initialization "
            "failed: <r>{error}</r>.",
            error=error,
        )
        _state.counter = None
        _state.histogram = None
        return None

    if _state.counter is None or _state.histogram is None:
        return None
    return _state.counter, _state.histogram


def load_prometheus() -> tuple[Counter, Histogram] | None:
    """Load render metrics once, including under concurrent first use."""

    with _state_lock:
        return _load_prometheus()


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
    try:
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
            except Exception:
                counter_recorded = False
            try:
                histogram_metric.observe(duration, exemplar={"trace_id": trace_id})
                histogram_recorded = True
            except Exception:
                histogram_recorded = False
        else:
            counter_recorded = False
            histogram_recorded = False

        if not counter_recorded:
            counter_metric.inc()
        if not histogram_recorded:
            histogram_metric.observe(duration)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus metric export failed: "
            "<r>{error}</r>.",
            error=error,
        )


def _load_filehost_metrics_unlocked() -> (
    tuple[Counter, Counter, Gauge, Gauge, Gauge] | None
):
    try:
        if not is_prometheus_enabled():
            return None
        cached = (
            _state.filehost_upload_bytes,
            _state.filehost_dedup_hits,
            _state.filehost_active_mappings,
            _state.filehost_active_leases,
            _state.filehost_cleanup_capable,
        )
        if all(metric is not None for metric in cached):
            return cast("tuple[Counter, Counter, Gauge, Gauge, Gauge]", cached)
        if not ensure_prometheus_plugin_loaded(reason="filehost_metrics"):
            return None
        prometheus = _state.plugin or sys.modules.get("nonebot_plugin_prometheus")
        if prometheus is None:
            return None
        counter_cls = getattr(prometheus, "Counter", None)
        gauge_cls = getattr(prometheus, "Gauge", None)
        if not callable(counter_cls) or not callable(gauge_cls):
            return None
        _state.filehost_upload_bytes = cast(
            "Counter",
            counter_cls(
                _PROM_FILEHOST_UPLOAD_BYTES_NAME,
                "Bytes uploaded through the explicit htmlrender filehost adapter.",
            ),
        )
        _state.filehost_dedup_hits = cast(
            "Counter",
            counter_cls(
                _PROM_FILEHOST_DEDUP_HITS_NAME,
                "Filehost uploads avoided by content-addressed URL mappings.",
            ),
        )
        _state.filehost_active_mappings = cast(
            "Gauge",
            gauge_cls(
                _PROM_FILEHOST_ACTIVE_MAPPINGS_NAME,
                "Active process-local filehost URL mappings.",
            ),
        )
        _state.filehost_active_leases = cast(
            "Gauge",
            gauge_cls(
                _PROM_FILEHOST_ACTIVE_LEASES_NAME,
                "Active process-local filehost leases.",
            ),
        )
        _state.filehost_cleanup_capable = cast(
            "Gauge",
            gauge_cls(
                _PROM_FILEHOST_CLEANUP_CAPABLE_NAME,
                "Whether per-file physical cleanup is supported by the adapter.",
            ),
        )
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus filehost metric "
            "initialization failed: <r>{error}</r>.",
            error=error,
        )
        return None

    metrics = (
        _state.filehost_upload_bytes,
        _state.filehost_dedup_hits,
        _state.filehost_active_mappings,
        _state.filehost_active_leases,
        _state.filehost_cleanup_capable,
    )
    if any(metric is None for metric in metrics):
        return None
    return metrics


def _load_filehost_metrics() -> tuple[Counter, Counter, Gauge, Gauge, Gauge] | None:
    with _state_lock:
        return _load_filehost_metrics_unlocked()


def record_filehost_cache_metrics(
    event: str,
    value: int,
    active_mappings: int,
    active_leases: int,
    physical_cleanup_capable: int,
) -> None:
    """Record low-cardinality filehost counters and current-state gauges."""

    try:
        metrics = _load_filehost_metrics()
        if metrics is None:
            return
        upload_bytes, dedup_hits, mappings, leases, cleanup = metrics
        if event == "upload":
            upload_bytes.inc(value)
        elif event == "dedup":
            dedup_hits.inc(value)
        mappings.set(active_mappings)
        leases.set(active_leases)
        cleanup.set(physical_cleanup_capable)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus filehost metric export "
            "failed: <r>{error}</r>.",
            error=error,
        )


def _load_cache_metrics_unlocked() -> tuple[Counter, Gauge, Gauge] | None:
    try:
        if not is_prometheus_enabled():
            return None
        cached = (
            _state.cache_events,
            _state.cache_entries,
            _state.cache_resident_bytes,
        )
        if all(metric is not None for metric in cached):
            return cast("tuple[Counter, Gauge, Gauge]", cached)
        if not ensure_prometheus_plugin_loaded(reason="cache_metrics"):
            return None
        prometheus = _state.plugin or sys.modules.get("nonebot_plugin_prometheus")
        if prometheus is None:
            return None
        counter_cls = getattr(prometheus, "Counter", None)
        gauge_cls = getattr(prometheus, "Gauge", None)
        if not callable(counter_cls) or not callable(gauge_cls):
            return None
        _state.cache_events = cast(
            "Counter",
            counter_cls(
                _PROM_CACHE_EVENTS_NAME,
                "Cache events by bounded cache and event type.",
                ["cache", "event"],
            ),
        )
        _state.cache_entries = cast(
            "Gauge",
            gauge_cls(
                _PROM_CACHE_ENTRIES_NAME,
                "Current resident entries by bounded cache.",
                ["cache"],
            ),
        )
        _state.cache_resident_bytes = cast(
            "Gauge",
            gauge_cls(
                _PROM_CACHE_RESIDENT_BYTES_NAME,
                "Current resident bytes by byte-weighted cache.",
                ["cache"],
            ),
        )
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus cache metric "
            "initialization failed: <r>{error}</r>.",
            error=error,
        )
        return None

    metrics = (
        _state.cache_events,
        _state.cache_entries,
        _state.cache_resident_bytes,
    )
    if any(metric is None for metric in metrics):
        return None
    return metrics


def _load_cache_metrics() -> tuple[Counter, Gauge, Gauge] | None:
    with _state_lock:
        return _load_cache_metrics_unlocked()


def record_cache_metrics(
    cache: str,
    events: Mapping[str, int],
    entries: int,
    resident_bytes: int | None,
) -> None:
    """Record generic cache deltas and state with bounded labels."""

    try:
        metrics = _load_cache_metrics()
        if metrics is None:
            return
        event_counter, entries_gauge, resident_bytes_gauge = metrics
        for event, value in events.items():
            if value > 0:
                event_counter.labels(cache=cache, event=event).inc(value)
        entries_gauge.labels(cache=cache).set(entries)
        if resident_bytes is not None:
            resident_bytes_gauge.labels(cache=cache).set(resident_bytes)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Prometheus cache metric export "
            "failed: <r>{error}</r>.",
            error=error,
        )
