from types import SimpleNamespace
from typing import Any

import pytest
from pytest_mock import MockerFixture


def test_instrument_page_registers_and_detaches_collector(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import telemetry  # noqa: PLC0415
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        detach_page,
        get_page_collector,
        instrument_page,
    )

    page = mocker.MagicMock()

    assert not hasattr(telemetry, "_collectors")

    collector = instrument_page(page, page_name="render-page")

    assert collector.page_name == "render-page"
    assert get_page_collector(page) is collector
    assert page.on.call_count == 5
    assert [call.args[0] for call in page.on.call_args_list] == [
        "request",
        "response",
        "requestfailed",
        "domcontentloaded",
        "load",
    ]

    detach_page(page)
    assert get_page_collector(page) is None


def test_page_collectors_are_owned_by_each_page(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        detach_page,
        get_page_collector,
        instrument_page,
    )

    first_page = mocker.MagicMock()
    second_page = mocker.MagicMock()
    first = instrument_page(first_page, page_name="first")
    second = instrument_page(second_page, page_name="second")

    assert get_page_collector(first_page) is first
    assert get_page_collector(second_page) is second

    detach_page(first_page)
    assert get_page_collector(first_page) is None
    assert get_page_collector(second_page) is second


def test_page_telemetry_collector_tracks_request_response_and_failed(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        PageTelemetryCollector,
    )

    collector = PageTelemetryCollector(page_name="collector")
    request = SimpleNamespace(
        url="https://example.com/image.png",
        resource_type="image",
        method="GET",
        failure=None,
    )
    response = SimpleNamespace(request=request, status=200)

    timeline = iter([10.0, 10.015, 10.05])
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.perf_counter",
        side_effect=lambda: next(timeline),
    )

    request_obj: Any = request
    response_obj: Any = response
    collector.on_request(request_obj)
    collector.on_response(response_obj)
    collector.on_request_failed(request_obj)

    sample = collector.request_samples[id(request)]
    assert sample.status == 200
    assert sample.duration_ms == 50.0
    assert sample.failed is True
    assert sample.failure_text is None


def test_page_telemetry_collector_creates_sample_for_failed_orphan_request(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        PageTelemetryCollector,
    )

    collector = PageTelemetryCollector(page_name="collector")
    request = SimpleNamespace(
        url="https://example.com/app.js",
        resource_type="script",
        method="GET",
        failure="net::ERR_FAILED",
    )

    timeline = iter([20.0, 20.03])
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.perf_counter",
        side_effect=lambda: next(timeline),
    )

    request_obj: Any = request
    collector.on_request_failed(request_obj)

    sample = collector.request_samples[id(request)]
    assert sample.failed is True
    assert sample.failure_text == "net::ERR_FAILED"
    assert sample.duration_ms == 30.0


@pytest.mark.anyio
async def test_collect_navigation_timings_rounds_numeric_values(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        collect_navigation_timings,
    )

    page = mocker.AsyncMock()
    page.evaluate.return_value = {
        "dns": 1.234,
        "tcp": 2,
        "note": "ignored",
    }

    assert await collect_navigation_timings(page) == {
        "dns": 1.23,
        "tcp": 2.0,
    }


@pytest.mark.anyio
async def test_collect_navigation_timings_returns_empty_for_non_dict(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        collect_navigation_timings,
    )

    page = mocker.AsyncMock()
    page.evaluate.return_value = ["not-a-dict"]

    assert await collect_navigation_timings(page) == {}


@pytest.mark.anyio
async def test_collect_navigation_timings_handles_errors(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        collect_navigation_timings,
    )

    page = mocker.AsyncMock()
    page.evaluate.side_effect = RuntimeError("boom")
    logger_debug = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.logger.debug"
    )

    assert await collect_navigation_timings(page) == {}
    logger_debug.assert_called_once()


@pytest.mark.anyio
async def test_page_telemetry_collector_snapshot_summarizes_requests(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        PageTelemetryCollector,
        PageTelemetrySnapshot,
        RequestSample,
    )

    page = mocker.AsyncMock()
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.collect_navigation_timings",
        new=mocker.AsyncMock(return_value={"load": 3.21}),
    )

    collector = PageTelemetryCollector(
        page_name="snapshot-page",
        request_samples={
            1: RequestSample(
                url="https://example.com/index.html",
                resource_type="document",
                method="GET",
                start_time=0.0,
                duration_ms=10.0,
                status=200,
            ),
            2: RequestSample(
                url="https://example.com/app.js",
                resource_type="script",
                method="GET",
                start_time=0.0,
                duration_ms=20.0,
                failed=True,
                failure_text="net::ERR_FAILED",
            ),
        },
        domcontentloaded_ms=11.0,
        load_ms=13.0,
    )

    snapshot = await collector.snapshot(page)

    assert snapshot == PageTelemetrySnapshot(
        total_requests=2,
        failed_requests=1,
        average_request_ms=15.0,
        max_request_ms=20.0,
        domcontentloaded_ms=11.0,
        load_ms=13.0,
        resource_counts={"document": 1, "script": 1},
        navigation_timings_ms={"load": 3.21},
    )


@pytest.mark.anyio
async def test_log_page_telemetry_logs_snapshot_when_collector_exists(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        PageTelemetrySnapshot,
        log_page_telemetry,
    )

    page = object()
    collector = SimpleNamespace(
        snapshot=mocker.AsyncMock(
            return_value=PageTelemetrySnapshot(
                total_requests=2,
                failed_requests=1,
                average_request_ms=15.0,
                max_request_ms=20.0,
                domcontentloaded_ms=11.0,
                load_ms=13.0,
                resource_counts={"document": 1},
                navigation_timings_ms={"load": 3.21},
            )
        )
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.get_page_collector",
        return_value=collector,
    )
    logger_debug = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.logger.debug"
    )

    page_obj: Any = page
    await log_page_telemetry(page_obj, op="playwright.render_html")

    collector.snapshot.assert_awaited_once_with(page)
    logger_debug.assert_called_once()
    assert "playwright.render_html" in logger_debug.call_args.args[0]


@pytest.mark.anyio
async def test_log_page_telemetry_is_noop_without_collector(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.telemetry import (  # noqa: PLC0415
        log_page_telemetry,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.get_page_collector",
        return_value=None,
    )
    logger_debug = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.telemetry.logger.debug"
    )

    page_obj: Any = object()
    await log_page_telemetry(page_obj, op="playwright.render_html")

    logger_debug.assert_not_called()
