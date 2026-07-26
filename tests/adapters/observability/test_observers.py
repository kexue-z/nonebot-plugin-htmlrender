from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters import observability as telemetry
from nonebot_plugin_htmlrender.providers.sdk import HTMLKIT_PROVIDER_ID
from nonebot_plugin_htmlrender.rendering import ProviderExecutionError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_track_render_without_span_uses_console_fallback(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(telemetry, "normalize_backend", return_value="playwright")
    start_trace = mocker.patch.object(telemetry, "start_trace", return_value=None)
    perf_counter = mocker.patch.object(
        telemetry, "perf_counter", side_effect=[10.0, 10.25]
    )
    record_sentry = mocker.patch.object(telemetry, "record_sentry_metrics")
    record_prom = mocker.patch.object(telemetry, "record_prometheus_metrics")
    logger = mocker.patch.object(telemetry, "logger")

    async with telemetry.track_render(
        "render.html",
        backend="playwright",
        attrs={"k": "v"},
        sentry=True,
        prometheus=True,
    ):
        pass

    start_trace.assert_called_once_with(
        "render.html",
        "render.html",
        {"render.backend": "playwright", "k": "v"},
    )
    assert perf_counter.call_count == 2
    assert logger.opt.return_value.debug.call_count == 2
    record_sentry.assert_called_once_with("render.html", "playwright", "ok", 0.25)
    record_prom.assert_called_once_with("render.html", "playwright", "ok", 0.25, None)


@pytest.mark.anyio
async def test_track_render_with_span_records_attrs_and_error_status(
    mocker: MockerFixture,
) -> None:
    span = mocker.Mock()
    exit_context = mocker.Mock(return_value=False)

    class TraceContext:
        def __enter__(self) -> object:
            return span

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return exit_context(exc_type, exc, traceback)

    mocker.patch.object(telemetry, "normalize_backend", return_value="playwright")
    mocker.patch.object(telemetry, "start_trace", return_value=TraceContext())
    mocker.patch.object(telemetry, "perf_counter", side_effect=[20.0, 20.4])
    set_span_attr = mocker.patch.object(telemetry, "set_span_attribute")
    set_span_status = mocker.patch.object(telemetry, "set_span_status")
    mocker.patch.object(telemetry, "get_trace_id", return_value="trace-id")
    record_sentry = mocker.patch.object(telemetry, "record_sentry_metrics")
    record_prom = mocker.patch.object(telemetry, "record_prometheus_metrics")

    with pytest.raises(ValueError, match="boom"):
        async with telemetry.track_render(
            "render.template",
            backend="playwright",
            name="custom-name",
            attrs={"x": "1"},
            sentry=True,
            prometheus=True,
        ):
            raise ValueError("boom")

    set_span_status.assert_any_call(span, "error")
    set_span_attr.assert_any_call(span, "error.type", "ValueError")
    set_span_attr.assert_any_call(span, "render.backend", "playwright")
    set_span_attr.assert_any_call(span, "x", "1")
    set_span_attr.assert_any_call(span, "render.status", "error")
    assert exit_context.call_count == 1
    assert exit_context.call_args.args[0] is ValueError
    assert isinstance(exit_context.call_args.args[1], ValueError)
    assert exit_context.call_args.args[2] is not None
    assert record_sentry.call_count == 1
    assert record_sentry.call_args.args[:3] == (
        "render.template",
        "playwright",
        "error",
    )
    assert record_sentry.call_args.args[3] == pytest.approx(0.4)
    assert record_prom.call_count == 1
    assert record_prom.call_args.args[:3] == ("render.template", "playwright", "error")
    assert record_prom.call_args.args[3] == pytest.approx(0.4)
    assert record_prom.call_args.args[4] == "trace-id"


@pytest.mark.anyio
async def test_track_render_records_bounded_rendering_error_metadata(
    mocker: MockerFixture,
) -> None:
    span = mocker.Mock()
    mocker.patch.object(telemetry, "start_trace", return_value=nullcontext(span))
    mocker.patch.object(telemetry, "perf_counter", side_effect=[1.0, 2.0])
    set_span_attr = mocker.patch.object(telemetry, "set_span_attribute")
    mocker.patch.object(telemetry, "set_span_status")
    mocker.patch.object(telemetry, "get_trace_id", return_value=None)
    mocker.patch.object(telemetry, "record_sentry_metrics")

    with pytest.raises(ProviderExecutionError):
        async with telemetry.track_render("render.error", sentry=True):
            raise ProviderExecutionError(
                "Render failed.",
                source=RuntimeError("native failure"),
            )

    set_span_attr.assert_any_call(span, "error.type", "ProviderExecutionError")
    set_span_attr.assert_any_call(span, "error.message", "Render failed.")
    set_span_attr.assert_any_call(span, "error.cause_types", "RuntimeError")
    recorded = {entry.args[1]: entry.args[2] for entry in set_span_attr.call_args_list}
    assert recorded["error.message_truncated"] is False
    assert recorded["error.causes_truncated"] is False


@pytest.mark.anyio
async def test_track_render_isolates_trace_and_exporter_failures(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        telemetry,
        "start_trace",
        side_effect=RuntimeError("trace initialization failed"),
    )
    record_sentry = mocker.patch.object(
        telemetry,
        "record_sentry_metrics",
        side_effect=RuntimeError("sentry export failed"),
    )
    record_prometheus = mocker.patch.object(
        telemetry,
        "record_prometheus_metrics",
        side_effect=RuntimeError("prometheus export failed"),
    )

    async with telemetry.track_render(
        "render.safe",
        backend="takumi",
        sentry=True,
        prometheus=True,
    ):
        result = "rendered"

    assert result == "rendered"
    record_sentry.assert_called_once()
    record_prometheus.assert_called_once()


@pytest.mark.anyio
async def test_track_render_preserves_original_error_when_trace_exit_fails(
    mocker: MockerFixture,
) -> None:
    span = mocker.Mock()

    class BrokenExitContext:
        def __enter__(self) -> object:
            return span

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback
            raise RuntimeError("trace exit failed")

    mocker.patch.object(
        telemetry,
        "start_trace",
        return_value=BrokenExitContext(),
    )
    mocker.patch.object(telemetry, "record_sentry_metrics")
    mocker.patch.object(telemetry, "record_prometheus_metrics")

    with pytest.raises(ValueError, match="render failed"):
        async with telemetry.track_render(
            "render.error",
            backend="takumi",
            sentry=True,
            prometheus=True,
        ):
            raise ValueError("render failed")


@pytest.mark.anyio
async def test_track_render_isolates_trace_enter_failure(
    mocker: MockerFixture,
) -> None:
    class BrokenEnterContext:
        def __enter__(self) -> None:
            raise RuntimeError("trace enter failed")

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

    mocker.patch.object(
        telemetry,
        "start_trace",
        return_value=BrokenEnterContext(),
    )
    mocker.patch.object(telemetry, "record_sentry_metrics")
    mocker.patch.object(telemetry, "record_prometheus_metrics")

    async with telemetry.track_render(
        "render.safe",
        backend="takumi",
        sentry=True,
        prometheus=True,
    ):
        result = b"image"

    assert result == b"image"


def test_record_cache_metrics_isolates_each_exporter(
    mocker: MockerFixture,
) -> None:
    sentry_recorder = mocker.patch.object(
        telemetry,
        "record_sentry_cache_metrics",
        side_effect=RuntimeError("sentry failed"),
    )
    prometheus_recorder = mocker.patch.object(
        telemetry,
        "record_prometheus_cache_metrics",
    )

    telemetry.record_cache_metrics(
        "resource",
        {"hit": 1},
        2,
        64,
        sentry=True,
        prometheus=True,
    )

    sentry_recorder.assert_called_once_with("resource", {"hit": 1}, 2, 64)
    prometheus_recorder.assert_called_once_with("resource", {"hit": 1}, 2, 64)


def test_operation_observer_exports_only_to_its_selected_integrations(
    mocker: MockerFixture,
) -> None:
    start_trace = mocker.patch.object(telemetry, "start_trace", return_value=None)
    sentry_recorder = mocker.patch.object(telemetry, "record_sentry_metrics")
    prometheus_recorder = mocker.patch.object(telemetry, "record_prometheus_metrics")

    observer = telemetry.TelemetryOperationObserver(
        sentry=False,
        prometheus=True,
    )
    with observer.observe("render.one", {"render.backend": "playwright"}):
        pass

    start_trace.assert_not_called()
    sentry_recorder.assert_not_called()
    prometheus_recorder.assert_called_once()


@pytest.mark.parametrize(
    ("operation", "backend"),
    [
        ("htmlkit.rasterize_html", HTMLKIT_PROVIDER_ID),
        ("graphics.pillow.render_scene", "pillow"),
        ("graphics.skia.render_scene", "skia"),
    ],
)
def test_new_backend_observation_stubs_fan_out_to_both_exporters(
    operation: str,
    backend: str,
    mocker: MockerFixture,
) -> None:
    start_trace = mocker.patch.object(telemetry, "start_trace", return_value=None)
    mocker.patch.object(telemetry, "perf_counter", side_effect=[4.0, 4.25])
    sentry_recorder = mocker.patch.object(telemetry, "record_sentry_metrics")
    prometheus_recorder = mocker.patch.object(
        telemetry,
        "record_prometheus_metrics",
    )
    observer = telemetry.TelemetryOperationObserver(
        sentry=True,
        prometheus=True,
    )

    with observer.observe(
        operation,
        {
            "render.backend": backend,
            "render.format": "png",
        },
    ):
        pass

    start_trace.assert_called_once_with(
        operation,
        operation,
        {
            "render.backend": backend,
            "render.format": "png",
        },
    )
    sentry_recorder.assert_called_once_with(
        operation,
        backend,
        "ok",
        0.25,
    )
    prometheus_recorder.assert_called_once_with(
        operation,
        backend,
        "ok",
        0.25,
        None,
    )


def test_cache_observer_exports_only_to_its_selected_integrations(
    mocker: MockerFixture,
) -> None:
    sentry_recorder = mocker.patch.object(telemetry, "record_sentry_cache_metrics")
    prometheus_recorder = mocker.patch.object(
        telemetry,
        "record_prometheus_cache_metrics",
    )

    observer = telemetry.TelemetryCacheObserver(sentry=True, prometheus=False)
    observer.record("resource", {"hit": 1}, 2, 64)

    sentry_recorder.assert_called_once_with("resource", {"hit": 1}, 2, 64)
    prometheus_recorder.assert_not_called()
