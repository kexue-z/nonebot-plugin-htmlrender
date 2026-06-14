from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.utils.telemetry import common

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_get_config_value_and_normalize_backend(mocker: MockerFixture) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.common.get_driver",
        return_value=SimpleNamespace(config=SimpleNamespace(sentry_dsn="dsn-value")),
    )

    assert common.get_config_value("sentry_dsn") == "dsn-value"
    assert common.normalize_backend(None) == "unknown"
    assert common.normalize_backend(RenderBackend.PLAYWRIGHT) == "playwright"
    assert common.normalize_backend("custom") == "custom"


def test_metric_params_cache_and_signature_failure(mocker: MockerFixture) -> None:
    def fn_ok(name: str, value: int) -> None:
        del name, value

    common._metric_param_cache.clear()
    params = common.metric_params(fn_ok)
    assert params == {"name", "value"}

    signature = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.common.inspect.signature"
    )
    signature.side_effect = ValueError("bad signature")

    class UninspectableCallable:
        __signature__ = object()

        def __call__(self, *_args, **_kwargs):
            return None

    fn_bad = UninspectableCallable()
    common._metric_param_cache.pop(id(fn_bad), None)
    assert common.metric_params(fn_bad) == set()


def test_call_metric_handles_value_amount_and_positional(
    mocker: MockerFixture,
) -> None:
    value_fn = mocker.Mock()
    amount_fn = mocker.Mock()
    positional_fn = mocker.Mock()

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.common.metric_params",
        side_effect=[
            {"value", "unit", "tags"},
            {"amount", "attributes"},
            {"name"},
        ],
    )

    common.call_metric(
        value_fn,
        "metric.value",
        3,
        unit="second",
        tags={"k": "v"},
    )
    value_fn.assert_called_once_with(
        "metric.value",
        value=3,
        unit="second",
        tags={"k": "v"},
    )

    common.call_metric(
        amount_fn,
        "metric.amount",
        9,
        unit=None,
        tags={"k2": "v2"},
    )
    amount_fn.assert_called_once_with(
        "metric.amount",
        amount=9,
        attributes={"k2": "v2"},
    )

    common.call_metric(
        positional_fn,
        "metric.positional",
        7,
        unit="ms",
        tags={"k3": "v3"},
    )
    positional_fn.assert_called_once_with("metric.positional", 7)


def test_set_span_attribute_status_and_trace_id_paths() -> None:
    recorded: dict[str, object] = {}

    class SpanWithAttribute:
        def set_attribute(self, key: str, value: object) -> None:
            recorded[key] = value

    common.set_span_attribute(SpanWithAttribute(), "a", 1)
    assert recorded == {"a": 1}

    class SpanSetAttributeRaises:
        def __init__(self) -> None:
            self.data: dict[str, object] = {}

        def set_attribute(self, key: str, value: object) -> None:
            del key, value
            raise RuntimeError("fail")

        def set_data(self, key: str, value: object) -> None:
            self.data[key] = value

    fallback_span = SpanSetAttributeRaises()
    common.set_span_attribute(fallback_span, "b", 2)
    assert fallback_span.data == {"b": 2}

    class SpanStatus:
        def __init__(self) -> None:
            self.status = ""

        def set_status(self, status: str) -> None:
            self.status = status

    status_span = SpanStatus()
    common.set_span_status(status_span, "ok")
    assert status_span.status == "ok"

    class TraceIdObject:
        def to_string(self) -> str:
            return "trace-id"

    class SpanTrace:
        trace_id = TraceIdObject()

    assert common.get_trace_id(SpanTrace()) == "trace-id"

    class SpanTraceError:
        class _TraceId:
            def to_string(self) -> str:
                raise RuntimeError("oops")

        trace_id = _TraceId()

    assert common.get_trace_id(SpanTraceError()) is None
