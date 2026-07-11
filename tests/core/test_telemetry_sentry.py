from __future__ import annotations

import types
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.utils.telemetry import sentry

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _reset_sentry_state() -> None:
    sentry._state.checked = False
    sentry._state.sdk = None


def test_sentry_enablement_flags(mocker: MockerFixture) -> None:
    values = {
        "sentry_dsn": "dsn",
        "sentry_traces_sample_rate": 1.0,
        "sentry_traces_sampler": None,
        "sentry_profiles_sample_rate": None,
        "sentry_profiles_sampler": "sampler",
        "sentry_profile_session_sample_rate": None,
    }
    mocker.patch.object(sentry, "get_config_value", side_effect=values.get)

    assert sentry.is_sentry_enabled() is True
    assert sentry.is_sentry_tracing_enabled() is True
    assert sentry.is_sentry_profiling_enabled() is True


def test_load_sentry_returns_cached_state(mocker: MockerFixture) -> None:
    _reset_sentry_state()
    cached_sdk = types.ModuleType("sentry_sdk_cached")
    sentry._state.checked = True
    sentry._state.sdk = cached_sdk
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    assert sentry.load_sentry() is cached_sdk


def test_load_sentry_handles_disabled_and_missing_plugin(mocker: MockerFixture) -> None:
    _reset_sentry_state()
    enabled = mocker.patch.object(sentry, "is_sentry_enabled", return_value=False)
    find_spec = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.find_spec", return_value=None
    )
    assert sentry.load_sentry() is None
    find_spec.assert_not_called()

    _reset_sentry_state()
    enabled.return_value = True
    assert sentry.load_sentry() is None

    _reset_sentry_state()
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.find_spec",
        return_value=object(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.require",
        side_effect=RuntimeError("missing"),
    )
    assert sentry.load_sentry() is None


def test_load_sentry_isolates_plugin_discovery_failure(
    mocker: MockerFixture,
) -> None:
    _reset_sentry_state()
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.find_spec",
        side_effect=RuntimeError("discovery failed"),
    )

    assert sentry.load_sentry() is None


def test_load_sentry_requires_plugin_and_reads_sdk_module(
    mocker: MockerFixture,
) -> None:
    _reset_sentry_state()
    fake_sdk = types.SimpleNamespace(name="fake")
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.find_spec",
        return_value=object(),
    )
    require = mocker.patch("nonebot_plugin_htmlrender.utils.telemetry.sentry.require")
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.sys.modules"
    )
    sys_modules.get.return_value = fake_sdk

    assert sentry.load_sentry() is fake_sdk
    require.assert_called_once_with("nonebot_plugin_sentry")


def test_record_metrics_respects_guards_and_reports(mocker: MockerFixture) -> None:
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=False)
    sentry.record_metrics("render.html", "playwright", "ok", 0.1)

    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch.object(sentry, "load_sentry", return_value=None)
    sentry.record_metrics("render.html", "playwright", "ok", 0.1)

    fake_metrics = types.SimpleNamespace(
        count=mocker.Mock(),
        distribution=mocker.Mock(),
    )
    fake_sdk = types.SimpleNamespace(metrics=fake_metrics)
    mocker.patch.object(sentry, "load_sentry", return_value=fake_sdk)
    call_metric = mocker.patch.object(sentry, "call_metric")

    sentry.record_metrics("render.html", "playwright", "ok", 0.123)

    assert call_metric.call_count == 2
    assert call_metric.call_args_list[0].args[0] is fake_metrics.count
    assert call_metric.call_args_list[1].args[0] is fake_metrics.distribution


def test_record_metrics_is_failure_isolated(mocker: MockerFixture) -> None:
    fake_metrics = types.SimpleNamespace(
        count=mocker.Mock(),
        distribution=mocker.Mock(),
    )
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch.object(
        sentry,
        "load_sentry",
        return_value=types.SimpleNamespace(metrics=fake_metrics),
    )
    mocker.patch.object(sentry, "call_metric", side_effect=RuntimeError("export"))

    sentry.record_metrics("render.html", "takumi", "ok", 0.1)


def test_record_metrics_uses_real_sentry_2_count_api(
    mocker: MockerFixture,
) -> None:
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.client import Client  # noqa: PLC0415
    from sentry_sdk.transport import Transport  # noqa: PLC0415

    class DiscardTransport(Transport):
        def capture_envelope(self, envelope: object) -> None:
            del envelope

    captured: list[dict[str, object]] = []
    client = Client(
        dsn="https://public@example.com/1",
        enable_metrics=True,
        transport=DiscardTransport,
    )

    def capture_metric(metric: dict[str, object], *, scope: object) -> None:
        del scope
        captured.append(metric)

    mocker.patch.object(client, "_capture_metric", side_effect=capture_metric)
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch.object(sentry, "load_sentry", return_value=sentry_sdk)

    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(client)
        sentry.record_metrics("render.html", "takumi", "ok", 0.125)

    counter = next(metric for metric in captured if metric["type"] == "counter")
    assert counter["name"] == "nonebot.htmlrender.count"
    assert counter["value"] == 1.0
    assert counter["attributes"] == {
        "op": "render.html",
        "backend": "takumi",
        "status": "ok",
    }


def test_record_metrics_is_noop_when_metrics_module_missing(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch.object(
        sentry, "load_sentry", return_value=types.SimpleNamespace(metrics=None)
    )
    call_metric = mocker.patch.object(sentry, "call_metric")

    sentry.record_metrics("render.html", "playwright", "ok", 0.1)

    call_metric.assert_not_called()


def test_record_filehost_cache_metrics_uses_count_and_gauge(
    mocker: MockerFixture,
) -> None:
    metrics = types.SimpleNamespace(count=mocker.Mock(), gauge=mocker.Mock())
    mocker.patch.object(sentry, "is_sentry_enabled", return_value=True)
    mocker.patch.object(
        sentry,
        "load_sentry",
        return_value=types.SimpleNamespace(metrics=metrics),
    )
    call_metric = mocker.patch.object(sentry, "call_metric")

    sentry.record_filehost_cache_metrics("upload", 512, 4, 2, 0)

    assert call_metric.call_count == 4
    assert call_metric.call_args_list[0].args[:3] == (
        metrics.count,
        "nonebot.htmlrender.filehost.upload_bytes",
        512,
    )
    assert [call.args[2] for call in call_metric.call_args_list[1:]] == [4, 2, 0]


def test_start_trace_returns_none_for_unavailable_paths(mocker: MockerFixture) -> None:
    mocker.patch.object(sentry, "load_sentry", return_value=None)
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=True)
    assert sentry.start_trace("op", "name", {"a": "1"}) is None

    mocker.patch.object(sentry, "load_sentry", return_value=types.SimpleNamespace())
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=False)
    assert sentry.start_trace("op", "name", {"a": "1"}) is None

    sdk_without_start = types.SimpleNamespace(start_transaction=None, start_span=None)
    mocker.patch.object(sentry, "load_sentry", return_value=sdk_without_start)
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=True)
    assert sentry.start_trace("op", "name", {"a": "1"}) is None


def test_start_trace_selects_root_transaction_or_child_span(
    mocker: MockerFixture,
) -> None:
    start_transaction = mocker.Mock(return_value="transaction")
    start_span = mocker.Mock(return_value="span")
    current_span = mocker.Mock(return_value=None)
    sdk = types.SimpleNamespace(
        get_current_span=current_span,
        start_transaction=start_transaction,
        start_span=start_span,
    )
    mocker.patch.object(sentry, "load_sentry", return_value=sdk)
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=True)
    set_attribute = mocker.patch.object(sentry, "set_span_attribute")
    result = sentry.start_trace("render", "render.name", {"k": "v"})
    assert result == "transaction"
    start_transaction.assert_called_once_with(
        op="render",
        name="render.name",
        source="task",
    )
    set_attribute.assert_called_once_with("transaction", "k", "v")
    start_span.assert_not_called()

    current_span.return_value = object()
    result2 = sentry.start_trace("render2", "render.desc", {"x": "y"})
    assert result2 == "span"
    start_span.assert_called_once_with(
        op="render2",
        name="render.desc",
    )
    set_attribute.assert_called_with("span", "x", "y")


def test_start_trace_uses_real_sentry_2_context_manager(
    mocker: MockerFixture,
) -> None:
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.client import Client  # noqa: PLC0415
    from sentry_sdk.transport import Transport  # noqa: PLC0415

    class DiscardTransport(Transport):
        def capture_envelope(self, envelope: object) -> None:
            del envelope

    mocker.patch.object(sentry, "load_sentry", return_value=sentry_sdk)
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=True)

    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(
            Client(
                dsn="https://public@example.com/1",
                traces_sample_rate=1.0,
                transport=DiscardTransport,
            )
        )
        trace_context = sentry.start_trace(
            "takumi.render_html",
            "takumi.render_html",
            {"render.backend": "takumi"},
        )
        assert trace_context is not None
        with trace_context as transaction:
            assert transaction.op == "takumi.render_html"
            assert transaction.name == "takumi.render_html"
            assert sentry_sdk.get_current_span() is transaction

        assert transaction.timestamp is not None

        with sentry_sdk.start_transaction(op="parent", name="parent") as parent:
            child_context = sentry.start_trace("child", "child", None)
            assert child_context is not None
            with child_context as child:
                assert child.parent_span_id == parent.span_id
