from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import inspect
from time import perf_counter

from nonebot.log import logger


@dataclass(slots=True)
class RequestSample:
    """单个请求的遥测采样数据。"""

    url: str
    resource_type: str
    method: str
    start_time: float
    duration_ms: float | None = None
    status: int | None = None
    failed: bool = False
    failure_text: str | None = None


@dataclass(slots=True)
class PageTelemetrySnapshot:
    """单次渲染页面的遥测快照，便于上报或日志输出。"""

    total_requests: int
    failed_requests: int
    average_request_ms: float
    max_request_ms: float
    domcontentloaded_ms: float | None
    load_ms: float | None
    resource_counts: dict[str, int]
    navigation_timings_ms: dict[str, float]


@dataclass
class PageTelemetryCollector:
    """收集单个 Playwright 页面的请求与导航时序。"""

    page_name: str
    start_time: float = field(default_factory=perf_counter)
    request_samples: dict[int, RequestSample] = field(default_factory=dict)
    domcontentloaded_ms: float | None = None
    load_ms: float | None = None

    def on_request(self, request: object) -> None:
        """记录页面发起的请求。"""
        url = getattr(request, "url", "")
        resource_type = getattr(request, "resource_type", "")
        method = getattr(request, "method", "")
        self.request_samples[id(request)] = RequestSample(
            url=url if isinstance(url, str) else "",
            resource_type=resource_type if isinstance(resource_type, str) else "",
            method=method if isinstance(method, str) else "",
            start_time=perf_counter(),
        )

    def on_response(self, response: object) -> None:
        """记录请求的响应信息。"""
        request = getattr(response, "request", None)
        sample = self.request_samples.get(id(request))
        if sample is None:
            return
        sample.duration_ms = round((perf_counter() - sample.start_time) * 1000, 2)
        status = getattr(response, "status", None)
        sample.status = status if isinstance(status, int) else None

    def on_request_failed(self, request: object) -> None:
        """记录失败的请求信息。"""
        sample = self.request_samples.get(id(request))
        if sample is None:
            url = getattr(request, "url", "")
            resource_type = getattr(request, "resource_type", "")
            method = getattr(request, "method", "")
            sample = RequestSample(
                url=url if isinstance(url, str) else "",
                resource_type=resource_type if isinstance(resource_type, str) else "",
                method=method if isinstance(method, str) else "",
                start_time=perf_counter(),
            )
            self.request_samples[id(request)] = sample
        sample.duration_ms = round((perf_counter() - sample.start_time) * 1000, 2)
        sample.failed = True
        failure = getattr(request, "failure", None)
        if isinstance(failure, str):
            sample.failure_text = failure

    def mark_domcontentloaded(self) -> None:
        """标记 DOMContentLoaded 事件时间。"""
        self.domcontentloaded_ms = round((perf_counter() - self.start_time) * 1000, 2)

    def mark_load(self) -> None:
        """标记 load 事件时间。"""
        self.load_ms = round((perf_counter() - self.start_time) * 1000, 2)

    async def snapshot(self, page: object) -> PageTelemetrySnapshot:
        """生成页面遥测数据快照。

        Args:
            page: Playwright 页面对象，用于收集导航计时。

        Returns:
            包含请求统计和导航计时的遥测快照。
        """
        request_durations = [
            sample.duration_ms
            for sample in self.request_samples.values()
            if sample.duration_ms is not None
        ]
        resource_counts = dict(
            Counter(sample.resource_type for sample in self.request_samples.values())
        )
        navigation_timings_ms = await collect_navigation_timings(page)
        return PageTelemetrySnapshot(
            total_requests=len(self.request_samples),
            failed_requests=sum(
                1 for sample in self.request_samples.values() if sample.failed
            ),
            average_request_ms=round(
                sum(request_durations) / len(request_durations),
                2,
            )
            if request_durations
            else 0.0,
            max_request_ms=max(request_durations, default=0.0),
            domcontentloaded_ms=self.domcontentloaded_ms,
            load_ms=self.load_ms,
            resource_counts=resource_counts,
            navigation_timings_ms=navigation_timings_ms,
        )


_COLLECTOR_ATTRIBUTE = "_htmlrender_page_telemetry_collector"


def instrument_page(page: object, *, page_name: str) -> PageTelemetryCollector:
    """为页面安装遥测事件监听器。

    Args:
        page: Playwright 页面对象。
        page_name: 页面标识名称，用于日志和追踪。

    Returns:
        关联到该页面的遥测收集器。
    """
    collector = PageTelemetryCollector(page_name=page_name)
    setattr(page, _COLLECTOR_ATTRIBUTE, collector)
    on = getattr(page, "on", None)
    if callable(on):
        on("request", collector.on_request)
        on("response", collector.on_response)
        on("requestfailed", collector.on_request_failed)
        on("domcontentloaded", lambda _page: collector.mark_domcontentloaded())
        on("load", lambda _page: collector.mark_load())
    return collector


def detach_page(page: object) -> None:
    """移除页面关联的遥测收集器。"""
    try:
        delattr(page, _COLLECTOR_ATTRIBUTE)
    except AttributeError:
        return


def get_page_collector(page: object) -> PageTelemetryCollector | None:
    """获取页面关联的遥测收集器。"""
    collector = getattr(page, _COLLECTOR_ATTRIBUTE, None)
    return collector if isinstance(collector, PageTelemetryCollector) else None


async def collect_navigation_timings(page: object) -> dict[str, float]:
    """收集页面导航性能计时数据（DNS、TCP、TTFB 等）。

    Args:
        page: Playwright 页面对象。

    Returns:
        各阶段耗时字典（毫秒），收集失败时返回空字典。
    """
    script = """
() => {
  const entries = performance.getEntriesByType("navigation");
  if (!entries.length) {
    return {};
  }
  const entry = entries[0];
  return {
    dns: entry.domainLookupEnd - entry.domainLookupStart,
    tcp: entry.connectEnd - entry.connectStart,
    tls: entry.secureConnectionStart > 0 ? entry.connectEnd - entry.secureConnectionStart : 0,
    ttfb: entry.responseStart - entry.requestStart,
    response: entry.responseEnd - entry.responseStart,
    dom_content_loaded: entry.domContentLoadedEventEnd - entry.startTime,
    load: entry.loadEventEnd - entry.startTime,
  };
}
"""
    try:
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return {}
        maybe_result = evaluate(script)
        if not inspect.isawaitable(maybe_result):
            return {}
        result = await maybe_result
    except Exception as exc:
        logger.debug(f"Failed to collect Playwright navigation timings: {exc}")
        return {}

    if not isinstance(result, dict):
        return {}

    timings: dict[str, float] = {}
    for key, value in result.items():
        if isinstance(key, str) and isinstance(value, int | float):
            timings[key] = round(float(value), 2)
    return timings


async def log_page_telemetry(page: object, *, op: str) -> None:
    """记录页面遥测数据到日志。

    Args:
        page: Playwright 页面对象。
        op: 当前操作名称，用于日志标识。
    """
    collector = get_page_collector(page)
    if collector is None:
        return

    snapshot = await collector.snapshot(page)
    logger.debug(
        f"Playwright telemetry {op} "
        f"requests={snapshot.total_requests} "
        f"failed={snapshot.failed_requests} "
        f"avg_ms={snapshot.average_request_ms} "
        f"max_ms={snapshot.max_request_ms} "
        f"resources={snapshot.resource_counts} "
        f"navigation={snapshot.navigation_timings_ms}"
    )
