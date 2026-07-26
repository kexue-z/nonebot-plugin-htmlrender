from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from nonebot.log import logger

from .common import OptionalPluginLoader, call_metric, set_span_attribute

if TYPE_CHECKING:
    from collections.abc import Mapping
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
_SENTRY_CACHE_EVENTS = "nonebot.htmlrender.cache.events"
_SENTRY_CACHE_ENTRIES = "nonebot.htmlrender.cache.entries"
_SENTRY_CACHE_RESIDENT_BYTES = "nonebot.htmlrender.cache.resident_bytes"

_plugin_loader = OptionalPluginLoader(
    plugin="nonebot_plugin_sentry",
    module="sentry_sdk",
)


def ensure_sentry_plugin_loaded(*, reason: str) -> bool:
    """Serialize optional-plugin discovery and bootstrap."""

    return _plugin_loader.load(reason=reason) is not None


def load_sentry() -> object | None:
    """Return the loaded Sentry SDK module, or ``None`` when unavailable."""
    return _plugin_loader.load(reason="runtime")


def record_metrics(op: str, backend: str, status: str, duration: float) -> None:
    """Report one render operation through Sentry metrics.

    Adapts to the available ``count``/``increment``/``incr`` and
    ``distribution`` interfaces; silently returns when the SDK or its
    metrics surface is unavailable.
    """
    try:
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
    """Create a Sentry transaction or span using the 2.x context-manager API.

    Creates a child span when an active span exists, otherwise a root
    transaction.  Returns ``None`` when the SDK is unavailable; sampling
    remains owned by the Sentry SDK.
    """
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
        if not isinstance(trace_obj, AbstractContextManager):
            raise TypeError("Sentry start callable did not return a context manager.")
        for key, value in (attrs or {}).items():
            set_span_attribute(trace_obj, key, value)
        return trace_obj
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


def record_cache_metrics(
    cache: str,
    events: Mapping[str, int],
    entries: int,
    resident_bytes: int | None,
) -> None:
    """Record generic cache deltas without exporting cache keys or paths."""

    try:
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
        if callable(count):
            for event, value in events.items():
                if value > 0:
                    call_metric(
                        count,
                        _SENTRY_CACHE_EVENTS,
                        value,
                        unit=None,
                        tags={"cache": cache, "event": event},
                    )
        if callable(gauge):
            tags = {"cache": cache}
            call_metric(
                gauge,
                _SENTRY_CACHE_ENTRIES,
                entries,
                unit=None,
                tags=tags,
            )
            if resident_bytes is not None:
                call_metric(
                    gauge,
                    _SENTRY_CACHE_RESIDENT_BYTES,
                    resident_bytes,
                    unit="byte",
                    tags=tags,
                )
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Sentry cache metric export failed: "
            "<r>{error}</r>.",
            error=error,
        )
