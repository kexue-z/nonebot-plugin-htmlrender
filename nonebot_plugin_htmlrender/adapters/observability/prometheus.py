from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

from nonebot.log import logger

from .common import OptionalPluginLoader

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    """Cache metric instances so registration happens exactly once."""

    def __init__(self) -> None:
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
_plugin_loader = OptionalPluginLoader(
    plugin="nonebot_plugin_prometheus",
    module="nonebot_plugin_prometheus",
)


def ensure_prometheus_plugin_loaded(*, reason: str) -> bool:
    """Serialize optional-plugin discovery and bootstrap."""

    return _plugin_loader.load(reason=reason) is not None


def _load_prometheus() -> tuple[Counter, Histogram] | None:
    """Return the render counter and duration histogram, creating them once.

    Metrics are created one by one: a constructor failure keeps every
    already-registered instance so a retry only creates the missing metric
    instead of tripping a duplicate name in the default registry. Returns
    ``None`` when the optional Prometheus plugin is unavailable or a metric
    is still missing.
    """
    try:
        if _state.counter is not None and _state.histogram is not None:
            return _state.counter, _state.histogram
        prometheus = _plugin_loader.load(reason="runtime")
        if prometheus is None:
            return None

        counter_cls = getattr(prometheus, "Counter", None)
        histogram_cls = getattr(prometheus, "Histogram", None)
        if counter_cls is None or histogram_cls is None:
            return None

        if _state.counter is None:
            _state.counter = counter_cls(
                _PROM_COUNTER_NAME,
                "Total render operations.",
                ["op", "backend", "status"],
            )
        if _state.histogram is None:
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
    """Record one render operation, attaching an exemplar when possible.

    Silently returns when the integration is unavailable; older client
    versions without exemplar support fall back to a plain report.
    """
    try:
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
        cached = (
            _state.filehost_upload_bytes,
            _state.filehost_dedup_hits,
            _state.filehost_active_mappings,
            _state.filehost_active_leases,
            _state.filehost_cleanup_capable,
        )
        upload_bytes, dedup_hits, mappings, leases, cleanup = cached
        if (
            upload_bytes is not None
            and dedup_hits is not None
            and mappings is not None
            and leases is not None
            and cleanup is not None
        ):
            return upload_bytes, dedup_hits, mappings, leases, cleanup
        prometheus = _plugin_loader.load(reason="filehost_metrics")
        if prometheus is None:
            return None
        counter_cls = getattr(prometheus, "Counter", None)
        gauge_cls = getattr(prometheus, "Gauge", None)
        if not callable(counter_cls) or not callable(gauge_cls):
            return None
        # Get-or-create per metric: partially registered instances survive a
        # later constructor failure so the retry never re-registers them.
        if _state.filehost_upload_bytes is None:
            _state.filehost_upload_bytes = cast(
                "Counter",
                counter_cls(
                    _PROM_FILEHOST_UPLOAD_BYTES_NAME,
                    "Bytes uploaded through the explicit htmlrender filehost adapter.",
                ),
            )
        if _state.filehost_dedup_hits is None:
            _state.filehost_dedup_hits = cast(
                "Counter",
                counter_cls(
                    _PROM_FILEHOST_DEDUP_HITS_NAME,
                    "Filehost uploads avoided by content-addressed URL mappings.",
                ),
            )
        if _state.filehost_active_mappings is None:
            _state.filehost_active_mappings = cast(
                "Gauge",
                gauge_cls(
                    _PROM_FILEHOST_ACTIVE_MAPPINGS_NAME,
                    "Active process-local filehost URL mappings.",
                ),
            )
        if _state.filehost_active_leases is None:
            _state.filehost_active_leases = cast(
                "Gauge",
                gauge_cls(
                    _PROM_FILEHOST_ACTIVE_LEASES_NAME,
                    "Active process-local filehost leases.",
                ),
            )
        if _state.filehost_cleanup_capable is None:
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
        cached = (
            _state.cache_events,
            _state.cache_entries,
            _state.cache_resident_bytes,
        )
        events, entries, resident_bytes = cached
        if events is not None and entries is not None and resident_bytes is not None:
            return events, entries, resident_bytes
        prometheus = _plugin_loader.load(reason="cache_metrics")
        if prometheus is None:
            return None
        counter_cls = getattr(prometheus, "Counter", None)
        gauge_cls = getattr(prometheus, "Gauge", None)
        if not callable(counter_cls) or not callable(gauge_cls):
            return None
        # Get-or-create per metric: partially registered instances survive a
        # later constructor failure so the retry never re-registers them.
        if _state.cache_events is None:
            _state.cache_events = cast(
                "Counter",
                counter_cls(
                    _PROM_CACHE_EVENTS_NAME,
                    "Cache events by bounded cache and event type.",
                    ["cache", "event"],
                ),
            )
        if _state.cache_entries is None:
            _state.cache_entries = cast(
                "Gauge",
                gauge_cls(
                    _PROM_CACHE_ENTRIES_NAME,
                    "Current resident entries by bounded cache.",
                    ["cache"],
                ),
            )
        if _state.cache_resident_bytes is None:
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
