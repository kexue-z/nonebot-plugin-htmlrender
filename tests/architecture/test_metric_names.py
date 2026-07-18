"""Characterization of exported telemetry metric names and label sets.

Dashboards and alerting depend on these literals; the 0.8 rework must keep
them byte-identical. Any change here is a breaking observability change and
needs an explicit dashboard-migration decision first.
"""

from __future__ import annotations

import ast
from pathlib import Path
import types
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.adapters.observability import prometheus, sentry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pytest_mock import MockerFixture

EXPECTED_PROMETHEUS_LABELS: dict[str, tuple[str, ...]] = {
    "nonebot_htmlrender_operations_total": ("op", "backend", "status"),
    "nonebot_htmlrender_duration_seconds": ("op", "backend", "status"),
    "nonebot_htmlrender_filehost_upload_bytes": (),
    "nonebot_htmlrender_filehost_dedup_hits": (),
    "nonebot_htmlrender_filehost_active_url_mappings": (),
    "nonebot_htmlrender_filehost_active_leases": (),
    "nonebot_htmlrender_filehost_physical_cleanup_capable": (),
    "nonebot_htmlrender_cache_events": ("cache", "event"),
    "nonebot_htmlrender_cache_entries": ("cache",),
    "nonebot_htmlrender_cache_resident_bytes": ("cache",),
}

EXPECTED_SENTRY_NAMES: dict[str, str] = {
    "_SENTRY_METRIC_DURATION": "nonebot.htmlrender.duration",
    "_SENTRY_METRIC_COUNT": "nonebot.htmlrender.count",
    "_SENTRY_FILEHOST_UPLOAD_BYTES": "nonebot.htmlrender.filehost.upload_bytes",
    "_SENTRY_FILEHOST_DEDUP_HITS": "nonebot.htmlrender.filehost.dedup_hits",
    "_SENTRY_FILEHOST_ACTIVE_MAPPINGS": (
        "nonebot.htmlrender.filehost.active_url_mappings"
    ),
    "_SENTRY_FILEHOST_ACTIVE_LEASES": "nonebot.htmlrender.filehost.active_leases",
    "_SENTRY_FILEHOST_CLEANUP_CAPABLE": (
        "nonebot.htmlrender.filehost.physical_cleanup_capable"
    ),
    "_SENTRY_CACHE_EVENTS": "nonebot.htmlrender.cache.events",
    "_SENTRY_CACHE_ENTRIES": "nonebot.htmlrender.cache.entries",
    "_SENTRY_CACHE_RESIDENT_BYTES": "nonebot.htmlrender.cache.resident_bytes",
}

EXPECTED_PROMETHEUS_NAMES: dict[str, str] = {
    "_PROM_COUNTER_NAME": "nonebot_htmlrender_operations_total",
    "_PROM_HISTOGRAM_NAME": "nonebot_htmlrender_duration_seconds",
    "_PROM_FILEHOST_UPLOAD_BYTES_NAME": "nonebot_htmlrender_filehost_upload_bytes",
    "_PROM_FILEHOST_DEDUP_HITS_NAME": "nonebot_htmlrender_filehost_dedup_hits",
    "_PROM_FILEHOST_ACTIVE_MAPPINGS_NAME": (
        "nonebot_htmlrender_filehost_active_url_mappings"
    ),
    "_PROM_FILEHOST_ACTIVE_LEASES_NAME": ("nonebot_htmlrender_filehost_active_leases"),
    "_PROM_FILEHOST_CLEANUP_CAPABLE_NAME": (
        "nonebot_htmlrender_filehost_physical_cleanup_capable"
    ),
    "_PROM_CACHE_EVENTS_NAME": "nonebot_htmlrender_cache_events",
    "_PROM_CACHE_ENTRIES_NAME": "nonebot_htmlrender_cache_entries",
    "_PROM_CACHE_RESIDENT_BYTES_NAME": "nonebot_htmlrender_cache_resident_bytes",
}


def test_prometheus_metric_name_constants() -> None:
    for constant, expected in EXPECTED_PROMETHEUS_NAMES.items():
        value = getattr(prometheus, constant)
        assert value == expected, f"{constant} changed: {value!r}"


def test_sentry_metric_name_constants() -> None:
    for constant, expected in EXPECTED_SENTRY_NAMES.items():
        value = getattr(sentry, constant)
        assert value == expected, f"{constant} changed: {value!r}"


def _prometheus_constructed_labels() -> dict[str, tuple[str, ...]]:
    """Extract label lists from metric constructor calls in the source."""
    source_path = Path(prometheus.__file__)
    tree = ast.parse(source_path.read_text("utf-8"), filename=str(source_path))
    labels_by_name: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Name) or not first.id.startswith("_PROM_"):
            continue
        metric_name = getattr(prometheus, first.id)
        assert isinstance(metric_name, str)
        labels: tuple[str, ...] = ()
        for arg in node.args[1:]:
            if isinstance(arg, ast.List):
                labels = tuple(
                    element.value
                    for element in arg.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
        previous = labels_by_name.get(metric_name)
        assert previous is None or previous == labels, (
            f"{metric_name} constructed twice with different labels"
        )
        labels_by_name[metric_name] = labels
    return labels_by_name


def test_prometheus_label_sets() -> None:
    assert _prometheus_constructed_labels() == EXPECTED_PROMETHEUS_LABELS


class _RecordingMetrics:
    """Sentry metrics stand-in capturing (api, name, value, unit, tags)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float, str | None, dict[str, str]]] = []
        self._register()

    def _register(self) -> None:
        recorder = self.calls

        def increment(
            name: str,
            value: float,
            unit: str | None = None,
            tags: Mapping[str, str] | None = None,
        ) -> None:
            recorder.append(("increment", name, value, unit, dict(tags or {})))

        def distribution(
            name: str,
            value: float,
            unit: str | None = None,
            tags: Mapping[str, str] | None = None,
        ) -> None:
            recorder.append(("distribution", name, value, unit, dict(tags or {})))

        def gauge(
            name: str,
            value: float,
            unit: str | None = None,
            tags: Mapping[str, str] | None = None,
        ) -> None:
            recorder.append(("gauge", name, value, unit, dict(tags or {})))

        self.increment = increment
        self.distribution = distribution
        self.gauge = gauge


def _fake_sentry_sdk() -> tuple[types.SimpleNamespace, _RecordingMetrics]:
    metrics = _RecordingMetrics()
    return types.SimpleNamespace(metrics=metrics), metrics


def test_sentry_render_metrics_emit_expected_names_and_tags(
    mocker: MockerFixture,
) -> None:
    sdk, metrics = _fake_sentry_sdk()
    mocker.patch.object(sentry, "load_sentry", return_value=sdk)

    sentry.record_metrics("render.render_html", "takumi", "success", 1.25)

    assert metrics.calls == [
        (
            "increment",
            "nonebot.htmlrender.count",
            1,
            None,
            {"op": "render.render_html", "backend": "takumi", "status": "success"},
        ),
        (
            "distribution",
            "nonebot.htmlrender.duration",
            1.25,
            "second",
            {"op": "render.render_html", "backend": "takumi", "status": "success"},
        ),
    ]


def test_sentry_cache_metrics_emit_expected_names_and_tags(
    mocker: MockerFixture,
) -> None:
    sdk, metrics = _fake_sentry_sdk()
    mocker.patch.object(sentry, "load_sentry", return_value=sdk)

    sentry.record_cache_metrics(
        "resource", {"hit": 2, "miss": 0}, entries=5, resident_bytes=4096
    )

    assert metrics.calls == [
        (
            "increment",
            "nonebot.htmlrender.cache.events",
            2,
            None,
            {"cache": "resource", "event": "hit"},
        ),
        ("gauge", "nonebot.htmlrender.cache.entries", 5, None, {"cache": "resource"}),
        (
            "gauge",
            "nonebot.htmlrender.cache.resident_bytes",
            4096,
            "byte",
            {"cache": "resource"},
        ),
    ]


def test_sentry_filehost_metrics_emit_expected_names_and_tags(
    mocker: MockerFixture,
) -> None:
    sdk, metrics = _fake_sentry_sdk()
    mocker.patch.object(sentry, "load_sentry", return_value=sdk)

    sentry.record_filehost_cache_metrics(
        "upload",
        2048,
        active_mappings=3,
        active_leases=1,
        physical_cleanup_capable=0,
    )

    filehost_tags = {"component": "filehost"}
    assert metrics.calls == [
        (
            "increment",
            "nonebot.htmlrender.filehost.upload_bytes",
            2048,
            "byte",
            filehost_tags,
        ),
        (
            "gauge",
            "nonebot.htmlrender.filehost.active_url_mappings",
            3,
            None,
            filehost_tags,
        ),
        (
            "gauge",
            "nonebot.htmlrender.filehost.active_leases",
            1,
            None,
            filehost_tags,
        ),
        (
            "gauge",
            "nonebot.htmlrender.filehost.physical_cleanup_capable",
            0,
            None,
            filehost_tags,
        ),
    ]
