from __future__ import annotations

from contextlib import asynccontextmanager, suppress
from time import perf_counter
from typing import TYPE_CHECKING, AsyncIterator, Mapping

from nonebot.log import logger

from .common import get_trace_id, normalize_backend, set_span_attribute, set_span_status
from .prometheus import record_metrics as record_prometheus_metrics
from .sentry import is_sentry_profiling_enabled, start_trace
from .sentry import record_metrics as record_sentry_metrics

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.consts import RenderBackend


@asynccontextmanager
async def track_render(
    op: str,
    *,
    backend: RenderBackend | str | None = None,
    name: str | None = None,
    attrs: Mapping[str, str] | None = None,
) -> AsyncIterator[None]:
    """渲染操作遥测追踪的异步上下文管理器。

    在渲染操作前后自动创建追踪 span、记录持续时间和状态，
    并向 Sentry 和 Prometheus 报告指标。若 Sentry 不可用则降级为控制台日志。

    Args:
        op: 操作名称（如 "screenshot"、"html_to_pic"）。
        backend: 渲染后端标识。
        name: span 的显示名称，默认使用 op。
        attrs: 附加到 span 的自定义属性。

    Yields:
        无返回值，仅提供上下文作用域。

    Raises:
        Exception: 渲染操作中的异常会被重新抛出，同时标记 span 状态为 error。
    """
    backend_name = normalize_backend(backend)
    all_attrs = {"render.backend": backend_name}
    if is_sentry_profiling_enabled():
        all_attrs["render.sentry.profiling"] = "true"
    if attrs:
        all_attrs.update(attrs)

    span = start_trace(op, name or op, all_attrs)
    if span is None:
        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> Console telemetry fallback enabled op=<y>{op}</y> backend=<y>{backend}</y>.",
            op=op,
            backend=backend_name,
        )
    start_time = perf_counter()
    status = "ok"
    trace_id: str | None = None

    try:
        yield
    except Exception:
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
            with suppress(Exception):
                exit_span = getattr(span, "__exit__", None)
                if callable(exit_span):
                    exit_span(None, None, None)
        else:
            logger.opt(colors=True).debug(
                "<d>[htmlrender.telemetry]</d> Render perf op=<y>{op}</y> backend=<y>{backend}</y> status=<y>{status}</y> duration=<y>{duration:.6f}</y>s.",
                op=op,
                backend=backend_name,
                status=status,
                duration=duration,
            )

        record_sentry_metrics(op, backend_name, status, duration)
        record_prometheus_metrics(op, backend_name, status, duration, trace_id)
