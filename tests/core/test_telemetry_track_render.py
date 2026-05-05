from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.utils import telemetry

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_track_render_without_span_uses_console_fallback(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(telemetry, "normalize_backend", return_value="playwright")
    mocker.patch.object(telemetry, "is_sentry_profiling_enabled", return_value=False)
    start_trace = mocker.patch.object(telemetry, "start_trace", return_value=None)
    perf_counter = mocker.patch.object(
        telemetry, "perf_counter", side_effect=[10.0, 10.25]
    )
    record_sentry = mocker.patch.object(telemetry, "record_sentry_metrics")
    record_prom = mocker.patch.object(telemetry, "record_prometheus_metrics")
    logger = mocker.patch.object(telemetry, "logger")

    async with telemetry.track_render(
        "render.html", backend="playwright", attrs={"k": "v"}
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
    span.__exit__ = mocker.Mock(side_effect=RuntimeError("ignored"))

    mocker.patch.object(telemetry, "normalize_backend", return_value="playwright")
    mocker.patch.object(telemetry, "is_sentry_profiling_enabled", return_value=True)
    mocker.patch.object(telemetry, "start_trace", return_value=span)
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
        ):
            raise ValueError("boom")

    set_span_status.assert_any_call(span, "error")
    set_span_attr.assert_any_call(span, "render.backend", "playwright")
    set_span_attr.assert_any_call(span, "render.sentry.profiling", "true")
    set_span_attr.assert_any_call(span, "x", "1")
    set_span_attr.assert_any_call(span, "render.status", "error")
    span.__exit__.assert_called_once_with(None, None, None)
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
