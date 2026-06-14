from __future__ import annotations

import types
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.utils.telemetry import prometheus

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _reset_prometheus_state() -> None:
    prometheus._state.checked = False
    prometheus._state.plugin = None
    prometheus._state.counter = None
    prometheus._state.histogram = None


def test_is_prometheus_enabled_defaults_to_true(mocker: MockerFixture) -> None:
    mocker.patch.object(prometheus, "get_config_value", return_value=None)
    assert prometheus.is_prometheus_enabled() is True

    mocker.patch.object(prometheus, "get_config_value", return_value=False)
    assert prometheus.is_prometheus_enabled() is False


def test_load_prometheus_guard_paths(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=False)
    assert prometheus.load_prometheus() is None

    _reset_prometheus_state()
    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.find_spec",
        return_value=None,
    )
    assert prometheus.load_prometheus() is None

    _reset_prometheus_state()
    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.find_spec",
        return_value=object(),
    )
    mocker.patch("nonebot_plugin_htmlrender.utils.telemetry.prometheus.require")
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.sys.modules"
    )
    sys_modules.get.return_value = None
    assert prometheus.load_prometheus() is None


def test_load_prometheus_success_and_cache(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    counter_obj = object()
    histogram_obj = object()
    counter_cls = mocker.Mock(return_value=counter_obj)
    histogram_cls = mocker.Mock(return_value=histogram_obj)
    fake_module = types.SimpleNamespace(Counter=counter_cls, Histogram=histogram_cls)

    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.find_spec",
        return_value=object(),
    )
    require = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.require"
    )
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.sys.modules"
    )
    sys_modules.get.return_value = fake_module

    loaded = prometheus.load_prometheus()
    assert loaded == (counter_obj, histogram_obj)
    require.assert_called_once_with("nonebot_plugin_prometheus")
    assert prometheus._state.plugin is fake_module

    # cached path
    assert prometheus.load_prometheus() == (counter_obj, histogram_obj)
    assert counter_cls.call_count == 1
    assert histogram_cls.call_count == 1


def test_load_prometheus_init_exception_returns_none(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    logger_debug = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.logger.debug"
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("bad init")

    fake_module = types.SimpleNamespace(Counter=_raise, Histogram=_raise)
    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.find_spec",
        return_value=object(),
    )
    mocker.patch("nonebot_plugin_htmlrender.utils.telemetry.prometheus.require")
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.utils.telemetry.prometheus.sys.modules"
    )
    sys_modules.get.return_value = fake_module

    assert prometheus.load_prometheus() is None
    logger_debug.assert_called_once()
    assert prometheus._state.counter is None
    assert prometheus._state.histogram is None


def test_record_metrics_with_and_without_trace_id(mocker: MockerFixture) -> None:
    counter_metric = mocker.Mock()
    histogram_metric = mocker.Mock()
    counter = mocker.Mock(labels=mocker.Mock(return_value=counter_metric))
    histogram = mocker.Mock(labels=mocker.Mock(return_value=histogram_metric))

    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch.object(
        prometheus, "load_prometheus", return_value=(counter, histogram)
    )

    prometheus.record_metrics("render", "playwright", "ok", 0.5, trace_id="trace-id")
    counter_metric.inc.assert_called_once_with(1, exemplar={"trace_id": "trace-id"})
    histogram_metric.observe.assert_called_once_with(
        0.5, exemplar={"trace_id": "trace-id"}
    )

    counter_metric.reset_mock()
    histogram_metric.reset_mock()
    prometheus.record_metrics("render", "playwright", "ok", 0.6, trace_id=None)
    counter_metric.inc.assert_called_once_with()
    histogram_metric.observe.assert_called_once_with(0.6)


def test_record_metrics_falls_back_when_exemplar_unsupported(
    mocker: MockerFixture,
) -> None:
    counter_metric = mocker.Mock()
    counter_metric.inc.side_effect = [TypeError("no exemplar"), None]
    histogram_metric = mocker.Mock()
    histogram_metric.observe.side_effect = [TypeError("no exemplar"), None]
    counter = mocker.Mock(labels=mocker.Mock(return_value=counter_metric))
    histogram = mocker.Mock(labels=mocker.Mock(return_value=histogram_metric))

    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch.object(
        prometheus, "load_prometheus", return_value=(counter, histogram)
    )

    prometheus.record_metrics("render", "playwright", "ok", 0.75, trace_id="trace")

    assert counter_metric.inc.call_count == 2
    assert counter_metric.inc.call_args_list[1].args == ()
    assert histogram_metric.observe.call_count == 2
    assert histogram_metric.observe.call_args_list[1].args == (0.75,)


def test_record_metrics_guard_and_exception_fallbacks(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=False)
    load_prom = mocker.patch.object(prometheus, "load_prometheus")
    prometheus.record_metrics("render", "playwright", "ok", 1.0, trace_id="x")
    load_prom.assert_not_called()

    mocker.patch.object(prometheus, "is_prometheus_enabled", return_value=True)
    mocker.patch.object(prometheus, "load_prometheus", return_value=None)
    prometheus.record_metrics("render", "playwright", "ok", 1.0, trace_id="x")

    counter_metric = mocker.Mock()
    counter_metric.inc.side_effect = [RuntimeError("inc fail"), None]
    histogram_metric = mocker.Mock()
    histogram_metric.observe.side_effect = [RuntimeError("obs fail"), None]
    counter = mocker.Mock(labels=mocker.Mock(return_value=counter_metric))
    histogram = mocker.Mock(labels=mocker.Mock(return_value=histogram_metric))
    mocker.patch.object(
        prometheus, "load_prometheus", return_value=(counter, histogram)
    )

    prometheus.record_metrics("render", "playwright", "ok", 1.25, trace_id="trace")

    assert counter_metric.inc.call_count == 2
    assert counter_metric.inc.call_args_list[1].args == ()
    assert histogram_metric.observe.call_count == 2
    assert histogram_metric.observe.call_args_list[1].args == (1.25,)
