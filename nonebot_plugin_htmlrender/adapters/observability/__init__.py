from __future__ import annotations

from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
import sys
from time import perf_counter
from typing import TYPE_CHECKING, AsyncIterator, Iterator, Mapping

from nonebot.log import logger

from .common import get_trace_id, normalize_backend, set_span_attribute, set_span_status
from .prometheus import (
    record_cache_metrics as record_prometheus_cache_metrics,
)
from .prometheus import (
    record_filehost_cache_metrics as record_prometheus_filehost_cache_metrics,
)
from .prometheus import record_metrics as record_prometheus_metrics
from .sentry import is_sentry_profiling_enabled, start_trace
from .sentry import (
    record_cache_metrics as record_sentry_cache_metrics,
)
from .sentry import (
    record_filehost_cache_metrics as record_sentry_filehost_cache_metrics,
)
from .sentry import record_metrics as record_sentry_metrics

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from nonebot_plugin_htmlrender.providers.sdk import EngineId


class TelemetryCacheObserver:
    """Instance-configured cache observer over selected exporters."""

    def __init__(self, *, sentry: bool, prometheus: bool) -> None:
        self._sentry = sentry
        self._prometheus = prometheus

    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        record_cache_metrics(
            cache,
            events,
            entries,
            resident_bytes,
            sentry=self._sentry,
            prometheus=self._prometheus,
        )


@contextmanager
def _entered_trace(
    trace_context: object | None,
) -> Generator[object | None, None, None]:
    """Enter and finish a provider context without exposing provider failures."""
    if trace_context is None:
        yield None
        return

    try:
        enter = getattr(trace_context, "__enter__", None)
        exit_context = getattr(trace_context, "__exit__", None)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Cannot inspect trace provider "
            "context: <r>{error}</r>.",
            error=error,
        )
        yield None
        return
    if not callable(enter) or not callable(exit_context):
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Trace provider returned an invalid "
            "context manager."
        )
        yield None
        return

    try:
        span = enter()
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> Trace provider enter failed: "
            "<r>{error}</r>.",
            error=error,
        )
        yield None
        return

    try:
        yield span
    except BaseException:
        exc_type, exc, traceback = sys.exc_info()
        try:
            exit_context(exc_type, exc, traceback)
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> Trace provider exit failed: "
                "<r>{error}</r>.",
                error=error,
            )
        raise
    else:
        try:
            exit_context(None, None, None)
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> Trace provider exit failed: "
                "<r>{error}</r>.",
                error=error,
            )


def _record_metrics_safely(
    provider: str,
    recorder: Callable[..., object],
    *args: object,
) -> None:
    """Run one exporter without allowing observability to affect rendering."""
    if not callable(recorder):
        return
    try:
        recorder(*args)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.telemetry]</d> {provider} metric export failed: "
            "<r>{error}</r>.",
            provider=provider,
            error=error,
        )


def record_filehost_cache_metrics(
    event: str,
    value: int,
    active_mappings: int,
    active_leases: int,
    physical_cleanup_capable: int,
    *,
    sentry: bool,
    prometheus: bool,
) -> None:
    """Export one filehost cache event without affecting resource delivery."""

    args = (
        event,
        value,
        active_mappings,
        active_leases,
        physical_cleanup_capable,
    )
    if sentry:
        _record_metrics_safely(
            "Sentry",
            record_sentry_filehost_cache_metrics,
            *args,
        )
    if prometheus:
        _record_metrics_safely(
            "Prometheus",
            record_prometheus_filehost_cache_metrics,
            *args,
        )


def record_cache_metrics(
    cache: str,
    events: Mapping[str, int],
    entries: int,
    resident_bytes: int | None = None,
    *,
    sentry: bool,
    prometheus: bool,
) -> None:
    """Export low-cardinality cache event deltas and current capacity."""

    args = (cache, events, entries, resident_bytes)
    if sentry:
        _record_metrics_safely("Sentry", record_sentry_cache_metrics, *args)
    if prometheus:
        _record_metrics_safely("Prometheus", record_prometheus_cache_metrics, *args)


@contextmanager
def _operation_context(
    op: str,
    *,
    backend: EngineId | None = None,
    name: str | None = None,
    attrs: Mapping[str, str] | None = None,
    sentry: bool,
    prometheus: bool,
) -> Iterator[None]:
    """Span creation, timing, and metric fan-out shared by every entry point."""
    backend_name = normalize_backend(backend)
    all_attrs = {"render.backend": backend_name}
    profiling_enabled = False
    if sentry:
        try:
            profiling_enabled = is_sentry_profiling_enabled()
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> Cannot inspect Sentry profiling "
                "configuration: <r>{error}</r>.",
                error=error,
            )
    if profiling_enabled:
        all_attrs["render.sentry.profiling"] = "true"
    if attrs:
        all_attrs.update(attrs)

    trace_context = None
    if sentry:
        try:
            trace_context = start_trace(op, name or op, all_attrs)
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> Trace provider initialization "
                "failed: <r>{error}</r>.",
                error=error,
            )
    if trace_context is None:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Console telemetry fallback enabled op=<y>{op}</y> backend=<y>{backend}</y>.",
            op=op,
            backend=backend_name,
        )
    start_time = perf_counter()
    status = "ok"
    trace_id: str | None = None

    duration = 0.0
    try:
        with _entered_trace(trace_context) as span:
            try:
                yield
            except BaseException:
                status = "error"
                if span is not None:
                    set_span_status(span, status)
                raise
            finally:
                duration = perf_counter() - start_time
                if span is not None:
                    for key, value in all_attrs.items():
                        set_span_attribute(span, key, value)
                    set_span_attribute(span, "render.status", status)
                    set_span_attribute(span, "render.duration_seconds", duration)
                    trace_id = get_trace_id(span)
                    set_span_status(span, status)
                else:
                    logger.opt(colors=True).debug(
                        "<d>[htmlrender.telemetry]</d> Render perf op=<y>{op}</y> backend=<y>{backend}</y> status=<y>{status}</y> duration=<y>{duration:.6f}</y>s.",
                        op=op,
                        backend=backend_name,
                        status=status,
                        duration=duration,
                    )
    finally:
        if sentry:
            _record_metrics_safely(
                "Sentry",
                record_sentry_metrics,
                op,
                backend_name,
                status,
                duration,
            )
        if prometheus:
            _record_metrics_safely(
                "Prometheus",
                record_prometheus_metrics,
                op,
                backend_name,
                status,
                duration,
                trace_id,
            )


@asynccontextmanager
async def track_render(
    op: str,
    *,
    backend: EngineId | None = None,
    name: str | None = None,
    attrs: Mapping[str, str] | None = None,
    sentry: bool = False,
    prometheus: bool = False,
) -> AsyncIterator[None]:
    """渲染操作遥测追踪的异步上下文管理器。

    在渲染操作前后记录持续时间和状态，并仅向调用方显式选择的
    Sentry / Prometheus exporter 报告。未选择 Sentry 时使用控制台日志。

    Args:
        op: 操作名称（如 "screenshot"、"html_to_pic"）。
        backend: 渲染后端标识。
        name: span 的显示名称，默认使用 op。
        attrs: 附加到 span 的自定义属性。
        sentry: 是否向 Sentry exporter 输出。
        prometheus: 是否向 Prometheus exporter 输出。

    Yields:
        无返回值，仅提供上下文作用域。

    Raises:
        Exception: 渲染操作中的异常会被重新抛出，同时标记 span 状态为 error。
    """
    with _operation_context(
        op,
        backend=backend,
        name=name,
        attrs=attrs,
        sentry=sentry,
        prometheus=prometheus,
    ):
        yield


class TelemetryOperationObserver:
    """Instance-configured operation observer over selected exporters."""

    def __init__(self, *, sentry: bool, prometheus: bool) -> None:
        self._sentry = sentry
        self._prometheus = prometheus

    def observe(
        self,
        operation: str,
        attributes: Mapping[str, str],
    ) -> AbstractContextManager[None]:
        extra = dict(attributes)
        backend = extra.pop("render.backend", None)
        return _operation_context(
            operation,
            backend=backend,
            name=operation,
            attrs=extra,
            sentry=self._sentry,
            prometheus=self._prometheus,
        )
