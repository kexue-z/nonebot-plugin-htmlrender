from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.adapters.observability import common

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_normalize_backend_does_not_depend_on_nonebot_config() -> None:
    assert not hasattr(common, "get_config_value")
    assert common.normalize_backend(None) == "unknown"
    assert common.normalize_backend("playwright") == "playwright"
    assert common.normalize_backend("custom") == "custom"


def test_metric_params_and_signature_failure(mocker: MockerFixture) -> None:
    def fn_ok(name: str, value: int) -> None:
        del name, value

    params = common.metric_params(fn_ok)
    assert params == {"name", "value"}

    signature = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.inspect.signature"
    )
    signature.side_effect = ValueError("bad signature")

    class UninspectableCallable:
        __signature__ = object()

        def __call__(self, *_args, **_kwargs):
            return None

    fn_bad = UninspectableCallable()
    assert common.metric_params(fn_bad) == set()


def test_call_metric_handles_value_amount_and_positional(
    mocker: MockerFixture,
) -> None:
    value_fn = mocker.Mock()
    amount_fn = mocker.Mock()
    positional_fn = mocker.Mock()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.metric_params",
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

    class StringSpanTrace:
        trace_id = "real-sentry-trace-id"

    assert common.get_trace_id(StringSpanTrace()) == "real-sentry-trace-id"

    class SpanTraceError:
        class _TraceId:
            def to_string(self) -> str:
                raise RuntimeError("oops")

        trace_id = _TraceId()

    assert common.get_trace_id(SpanTraceError()) is None


def test_span_helpers_isolate_attribute_access_failures() -> None:
    class BrokenSpan:
        def __getattribute__(self, name: str) -> object:
            if name in {"set_attribute", "set_data", "set_status", "trace_id"}:
                raise RuntimeError(f"cannot access {name}")
            return super().__getattribute__(name)

    span = BrokenSpan()
    common.set_span_attribute(span, "render.backend", "takumi")
    common.set_span_status(span, "ok")
    assert common.get_trace_id(span) is None
