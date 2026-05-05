from __future__ import annotations

from contextlib import asynccontextmanager
import importlib
import inspect
from time import perf_counter
from typing import Any, AsyncIterator, Mapping

from nonebot import require
from nonebot.log import logger

from nonebot_plugin_htmlrender.consts import RenderBackend

_SENTRY_METRIC_DURATION = "nonebot.htmlrender.duration"
_SENTRY_METRIC_COUNT = "nonebot.htmlrender.count"
_PROM_COUNTER_NAME = "nonebot_htmlrender_operations_total"
_PROM_HISTOGRAM_NAME = "nonebot_htmlrender_duration_seconds"

_metric_param_cache: dict[int, set[str]] = {}


class _TelemetryState:
    def __init__(self) -> None:
        self.sentry_sdk: Any | None = None
        self.sentry_checked = False
        self.prom_checked = False
        self.prom_counter: Any | None = None
        self.prom_histogram: Any | None = None


_state = _TelemetryState()


def _load_sentry() -> Any | None:
    if _state.sentry_checked:
        return _state.sentry_sdk
    _state.sentry_checked = True
    try:
        require("nonebot_plugin_sentry")
    except Exception as exc:
        logger.debug("Sentry plugin not available: %s", exc)
        _state.sentry_sdk = None
        return None
    try:
        _state.sentry_sdk = importlib.import_module("sentry_sdk")
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.debug("Sentry SDK not available: %s", exc)
        _state.sentry_sdk = None
    return _state.sentry_sdk


def _load_prometheus() -> tuple[Any, Any] | None:
    if _state.prom_checked:
        if _state.prom_counter is None or _state.prom_histogram is None:
            return None
        return _state.prom_counter, _state.prom_histogram
    _state.prom_checked = True
    try:
        require("nonebot_plugin_prometheus")
    except Exception as exc:
        logger.debug("Prometheus plugin not available: %s", exc)
        return None
    try:
        prometheus = importlib.import_module("nonebot_plugin_prometheus")
        _state.prom_counter = prometheus.Counter(
            _PROM_COUNTER_NAME,
            "Total render operations.",
            ["op", "backend", "status"],
        )
        _state.prom_histogram = prometheus.Histogram(
            _PROM_HISTOGRAM_NAME,
            "Render operation duration in seconds.",
            ["op", "backend", "status"],
        )
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.debug("Prometheus client not available: %s", exc)
        _state.prom_counter = None
        _state.prom_histogram = None
        return None
    return _state.prom_counter, _state.prom_histogram


def _metric_params(fn: Any) -> set[str]:
    key = id(fn)
    cached = _metric_param_cache.get(key)
    if cached is not None:
        return cached
    try:
        params = set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = set()
    _metric_param_cache[key] = params
    return params


def _call_metric(
    fn: Any,
    name: str,
    value: float | int,
    *,
    unit: str | None,
    tags: Mapping[str, str],
) -> None:
    params = _metric_params(fn)
    kwargs: dict[str, Any] = {}
    if "unit" in params and unit is not None:
        kwargs["unit"] = unit
    if "tags" in params:
        kwargs["tags"] = dict(tags)
    if "attributes" in params:
        kwargs["attributes"] = dict(tags)
    if "value" in params:
        kwargs["value"] = value
        fn(name, **kwargs)
        return
    if "amount" in params:
        kwargs["amount"] = value
        fn(name, **kwargs)
        return
    fn(name, value, **kwargs)


def _record_sentry_metrics(
    op: str,
    backend: str,
    status: str,
    duration: float,
) -> None:
    sentry = _load_sentry()
    if sentry is None:
        return
    metrics = getattr(sentry, "metrics", None)
    if metrics is None:
        return
    tags = {"op": op, "backend": backend, "status": status}
    increment = getattr(metrics, "increment", None) or getattr(metrics, "incr", None)
    distribution = getattr(metrics, "distribution", None)
    if increment is not None:
        _call_metric(increment, _SENTRY_METRIC_COUNT, 1, unit=None, tags=tags)
    if distribution is not None:
        _call_metric(distribution, _SENTRY_METRIC_DURATION, duration, unit="second", tags=tags)


def _prometheus_inc(metric: Any, trace_id: str | None) -> None:
    if trace_id:
        try:
            metric.inc(1, exemplar={"trace_id": trace_id})
            return
        except TypeError:
            pass
    metric.inc()


def _prometheus_observe(metric: Any, duration: float, trace_id: str | None) -> None:
    if trace_id:
        try:
            metric.observe(duration, exemplar={"trace_id": trace_id})
            return
        except TypeError:
            pass
    metric.observe(duration)


def _record_prometheus_metrics(
    op: str,
    backend: str,
    status: str,
    duration: float,
    trace_id: str | None,
) -> None:
    metrics = _load_prometheus()
    if metrics is None:
        return
    counter, histogram = metrics
    labels = {"op": op, "backend": backend, "status": status}
    _prometheus_inc(counter.labels(**labels), trace_id)
    _prometheus_observe(histogram.labels(**labels), duration, trace_id)


def _normalize_backend(backend: RenderBackend | str | None) -> str:
    if backend is None:
        return "unknown"
    if isinstance(backend, RenderBackend):
        return backend.value
    return str(backend)


def _start_span(sentry: Any, op: str, name: str) -> Any | None:
    start_span = getattr(sentry, "start_span", None)
    if start_span is None:
        return None
    params = _metric_params(start_span)
    kwargs: dict[str, Any] = {}
    if "op" in params:
        kwargs["op"] = op
    if "name" in params:
        kwargs["name"] = name
    elif "description" in params:
        kwargs["description"] = name
    return start_span(**kwargs)


@asynccontextmanager
async def track_render(
    op: str,
    *,
    backend: RenderBackend | str | None = None,
    name: str | None = None,
) -> AsyncIterator[None]:
    sentry = _load_sentry()
    span = None
    span_cm = None
    if sentry is not None:
        span_cm = _start_span(sentry, op, name or op)
        span = span_cm
    backend_name = _normalize_backend(backend)
    start = perf_counter()
    status = "ok"
    try:
        if span_cm is None:
            yield None
        else:
            with span_cm:
                if span is not None and hasattr(span, "set_data"):
                    span.set_data("backend", backend_name)
                yield None
    except Exception:
        status = "error"
        raise
    finally:
        duration = perf_counter() - start
        trace_id = None
        if span is not None:
            trace_id = getattr(span, "trace_id", None)
            if trace_id is not None:
                trace_id = str(trace_id)
        _record_sentry_metrics(op, backend_name, status, duration)
        _record_prometheus_metrics(op, backend_name, status, duration, trace_id)
