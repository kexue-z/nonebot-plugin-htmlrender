from __future__ import annotations

import types
from typing import TYPE_CHECKING

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
    assert sentry.load_sentry() is cached_sdk
    del mocker


def test_load_sentry_handles_disabled_and_missing_plugin(mocker: MockerFixture) -> None:
    _reset_sentry_state()
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.sentry.find_spec", return_value=None
    )
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


def test_load_sentry_requires_plugin_and_reads_sdk_module(
    mocker: MockerFixture,
) -> None:
    _reset_sentry_state()
    fake_sdk = types.SimpleNamespace(name="fake")

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
        increment=mocker.Mock(),
        distribution=mocker.Mock(),
    )
    fake_sdk = types.SimpleNamespace(metrics=fake_metrics)
    mocker.patch.object(sentry, "load_sentry", return_value=fake_sdk)
    call_metric = mocker.patch.object(sentry, "call_metric")

    sentry.record_metrics("render.html", "playwright", "ok", 0.123)

    assert call_metric.call_count == 2
    assert call_metric.call_args_list[0].args[0] is fake_metrics.increment
    assert call_metric.call_args_list[1].args[0] is fake_metrics.distribution


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


def test_start_trace_builds_kwargs_for_name_and_description(
    mocker: MockerFixture,
) -> None:
    start_transaction = mocker.Mock(return_value="transaction")
    sdk = types.SimpleNamespace(start_transaction=start_transaction, start_span=None)
    mocker.patch.object(sentry, "load_sentry", return_value=sdk)
    mocker.patch.object(sentry, "is_sentry_tracing_enabled", return_value=True)

    mocker.patch.object(
        sentry,
        "metric_params",
        return_value={"op", "name", "source", "attributes"},
    )
    result = sentry.start_trace("render", "render.name", {"k": "v"})
    assert result == "transaction"
    start_transaction.assert_called_once_with(
        op="render",
        name="render.name",
        source="task",
        attributes={"k": "v"},
    )

    start_span = mocker.Mock(return_value="span")
    sdk2 = types.SimpleNamespace(start_transaction=None, start_span=start_span)
    mocker.patch.object(sentry, "load_sentry", return_value=sdk2)
    mocker.patch.object(
        sentry,
        "metric_params",
        return_value={"op", "description", "data"},
    )
    result2 = sentry.start_trace("render2", "render.desc", {"x": "y"})
    assert result2 == "span"
    start_span.assert_called_once_with(
        op="render2",
        description="render.desc",
        data={"x": "y"},
    )
