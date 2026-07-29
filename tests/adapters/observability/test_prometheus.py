from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import types
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.observability import common, prometheus

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _reset_prometheus_state() -> None:
    prometheus._plugin_loader._checked = False
    prometheus._plugin_loader._loaded = None
    prometheus._state.counter = None
    prometheus._state.histogram = None
    prometheus._state.filehost_upload_bytes = None
    prometheus._state.filehost_dedup_hits = None
    prometheus._state.filehost_active_mappings = None
    prometheus._state.filehost_active_leases = None
    prometheus._state.filehost_cleanup_capable = None
    prometheus._state.cache_events = None
    prometheus._state.cache_entries = None
    prometheus._state.cache_resident_bytes = None


def _module(**attributes: object) -> types.ModuleType:
    module = types.ModuleType("fake_prometheus")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


def _seed_loaded_module(module: types.ModuleType) -> None:
    prometheus._plugin_loader._checked = True
    prometheus._plugin_loader._loaded = module


def test_prometheus_exporter_does_not_read_nonebot_global_config() -> None:
    assert not hasattr(prometheus, "get_config_value")


def test_optional_plugin_loader_guard_paths(mocker: MockerFixture) -> None:
    loader = common.OptionalPluginLoader(plugin="fake_plugin", module="fake_module")
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.find_spec",
        return_value=None,
    )
    assert loader.load(reason="test") is None

    loader = common.OptionalPluginLoader(plugin="fake_plugin", module="fake_module")
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.find_spec",
        return_value=object(),
    )
    mocker.patch("nonebot_plugin_htmlrender.adapters.observability.common.require")
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.sys.modules"
    )
    sys_modules.get.return_value = None
    assert loader.load(reason="test") is None


def test_optional_plugin_loader_isolates_discovery_failure(
    mocker: MockerFixture,
) -> None:
    loader = common.OptionalPluginLoader(plugin="fake_plugin", module="fake_module")
    find_spec = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.find_spec",
        side_effect=RuntimeError("discovery failed"),
    )

    assert loader.load(reason="test") is None
    # Failure outcomes are cached: discovery runs at most once per process.
    assert loader.load(reason="test") is None
    find_spec.assert_called_once()


def test_optional_plugin_loader_isolates_require_failure(
    mocker: MockerFixture,
) -> None:
    loader = common.OptionalPluginLoader(plugin="fake_plugin", module="fake_module")
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.find_spec",
        return_value=object(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.require",
        side_effect=RuntimeError("missing"),
    )

    assert loader.load(reason="test") is None


def test_optional_plugin_loader_success_and_cache(mocker: MockerFixture) -> None:
    loader = common.OptionalPluginLoader(plugin="fake_plugin", module="fake_module")
    fake_module = types.ModuleType("fake_module")
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.find_spec",
        return_value=object(),
    )
    require = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.require"
    )
    sys_modules = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.observability.common.sys.modules"
    )
    sys_modules.get.return_value = fake_module

    assert loader.load(reason="first") is fake_module
    assert loader.load(reason="second") is fake_module
    require.assert_called_once_with("fake_plugin")


def test_load_prometheus_returns_none_without_plugin(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    mocker.patch.object(prometheus._plugin_loader, "load", return_value=None)
    assert prometheus.load_prometheus() is None


def test_load_prometheus_success_and_cache(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    counter_obj = object()
    histogram_obj = object()
    counter_cls = mocker.Mock(return_value=counter_obj)
    histogram_cls = mocker.Mock(return_value=histogram_obj)
    fake_module = _module(Counter=counter_cls, Histogram=histogram_cls)
    _seed_loaded_module(fake_module)

    loaded = prometheus.load_prometheus()
    assert loaded == (counter_obj, histogram_obj)

    # cached path
    assert prometheus.load_prometheus() == (counter_obj, histogram_obj)
    assert counter_cls.call_count == 1
    assert histogram_cls.call_count == 1


def test_load_prometheus_init_exception_returns_none(mocker: MockerFixture) -> None:
    _reset_prometheus_state()
    logger_opt = mocker.patch.object(prometheus.logger, "opt")

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bad init")

    _seed_loaded_module(_module(Counter=_raise, Histogram=_raise))

    assert prometheus.load_prometheus() is None
    logger_opt.return_value.warning.assert_called_once()
    assert prometheus._state.counter is None
    assert prometheus._state.histogram is None


def test_record_metrics_with_and_without_trace_id(mocker: MockerFixture) -> None:
    counter_metric = mocker.Mock()
    histogram_metric = mocker.Mock()
    counter = mocker.Mock(labels=mocker.Mock(return_value=counter_metric))
    histogram = mocker.Mock(labels=mocker.Mock(return_value=histogram_metric))

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


def test_record_metrics_is_failure_isolated(mocker: MockerFixture) -> None:
    counter = mocker.Mock()
    counter.labels.side_effect = RuntimeError("labels failed")
    histogram = mocker.Mock()
    mocker.patch.object(
        prometheus,
        "load_prometheus",
        return_value=(counter, histogram),
    )

    prometheus.record_metrics("render", "takumi", "ok", 1.0, trace_id=None)


def test_record_filehost_cache_metrics_updates_counter_and_gauges(
    mocker: MockerFixture,
) -> None:
    upload = mocker.Mock()
    dedup = mocker.Mock()
    mappings = mocker.Mock()
    leases = mocker.Mock()
    cleanup = mocker.Mock()
    mocker.patch.object(
        prometheus,
        "_load_filehost_metrics",
        return_value=(upload, dedup, mappings, leases, cleanup),
    )

    prometheus.record_filehost_cache_metrics("upload", 4096, 3, 2, 0)
    prometheus.record_filehost_cache_metrics("dedup", 1, 3, 2, 0)

    upload.inc.assert_called_once_with(4096)
    dedup.inc.assert_called_once_with(1)
    assert mappings.set.call_args_list == [mocker.call(3), mocker.call(3)]
    assert leases.set.call_args_list == [mocker.call(2), mocker.call(2)]
    assert cleanup.set.call_args_list == [mocker.call(0), mocker.call(0)]


def test_record_cache_metrics_updates_labeled_counter_and_gauges(
    mocker: MockerFixture,
) -> None:
    event_metric = mocker.Mock()
    event_counter = mocker.Mock()
    event_counter.labels.return_value = event_metric
    entries_metric = mocker.Mock()
    entries_gauge = mocker.Mock()
    entries_gauge.labels.return_value = entries_metric
    bytes_metric = mocker.Mock()
    bytes_gauge = mocker.Mock()
    bytes_gauge.labels.return_value = bytes_metric
    mocker.patch.object(
        prometheus,
        "_load_cache_metrics",
        return_value=(event_counter, entries_gauge, bytes_gauge),
    )

    prometheus.record_cache_metrics(
        "takumi_compiled",
        {"hit": 2, "eviction": 0},
        3,
        4096,
    )

    event_counter.labels.assert_called_once_with(
        cache="takumi_compiled",
        event="hit",
    )
    event_metric.inc.assert_called_once_with(2)
    entries_gauge.labels.assert_called_once_with(cache="takumi_compiled")
    entries_metric.set.assert_called_once_with(3)
    bytes_gauge.labels.assert_called_once_with(cache="takumi_compiled")
    bytes_metric.set.assert_called_once_with(4096)


def test_cache_metric_collectors_initialize_once_under_concurrency(
    mocker: MockerFixture,
) -> None:
    _reset_prometheus_state()
    events = object()
    entries = object()
    resident_bytes = object()
    counter_cls = mocker.Mock(return_value=events)
    gauge_cls = mocker.Mock(side_effect=[entries, resident_bytes])
    _seed_loaded_module(_module(Counter=counter_cls, Gauge=gauge_cls))

    with ThreadPoolExecutor(max_workers=8) as executor:
        loaded = list(
            executor.map(lambda _: prometheus._load_cache_metrics(), range(8))
        )

    assert loaded == [(events, entries, resident_bytes)] * 8
    assert counter_cls.call_count == 1
    assert gauge_cls.call_count == 2


_METRIC_LOADERS: dict[str, str] = {
    prometheus._PROM_COUNTER_NAME: "render",
    prometheus._PROM_HISTOGRAM_NAME: "render",
    prometheus._PROM_FILEHOST_UPLOAD_BYTES_NAME: "filehost",
    prometheus._PROM_FILEHOST_DEDUP_HITS_NAME: "filehost",
    prometheus._PROM_FILEHOST_ACTIVE_MAPPINGS_NAME: "filehost",
    prometheus._PROM_FILEHOST_ACTIVE_LEASES_NAME: "filehost",
    prometheus._PROM_FILEHOST_CLEANUP_CAPABLE_NAME: "filehost",
    prometheus._PROM_CACHE_EVENTS_NAME: "cache",
    prometheus._PROM_CACHE_ENTRIES_NAME: "cache",
    prometheus._PROM_CACHE_RESIDENT_BYTES_NAME: "cache",
}


@pytest.mark.parametrize("failing_metric", sorted(_METRIC_LOADERS))
def test_partial_registration_faults_recover_without_duplicates(
    failing_metric: str,
) -> None:
    """One constructor fault per position; the retry must recover.

    The fake registry raises on duplicate names exactly like the
    prometheus_client default registry, so a loader that either resets or
    re-creates already-registered instances fails this test.
    """
    _reset_prometheus_state()
    registered: set[str] = set()
    failed_once: set[str] = set()

    def construct(name: str, *args: object, **kwargs: object) -> object:
        del args, kwargs
        if name == failing_metric and name not in failed_once:
            failed_once.add(name)
            raise RuntimeError(f"injected constructor failure for {name}")
        if name in registered:
            raise ValueError(f"Duplicated timeseries in CollectorRegistry: {name}")
        registered.add(name)
        return types.SimpleNamespace(name=name)

    _seed_loaded_module(
        _module(Counter=construct, Histogram=construct, Gauge=construct)
    )
    loaders = {
        "render": prometheus.load_prometheus,
        "filehost": prometheus._load_filehost_metrics,
        "cache": prometheus._load_cache_metrics,
    }
    loader = loaders[_METRIC_LOADERS[failing_metric]]

    assert loader() is None
    recovered = loader()
    assert recovered is not None
    assert all(metric is not None for metric in recovered)
    # The failing position was created exactly once after recovery.
    assert failing_metric in registered
