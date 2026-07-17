from __future__ import annotations

from io import BytesIO
import threading
from typing import TYPE_CHECKING, TypeVar

import anyio
from anyio import wait_all_tasks_blocked
from anyio.lowlevel import checkpoint
from anyio.to_thread import run_sync as run_sync_in_worker
from PIL import Image
import pytest

from nonebot_plugin_htmlrender.adapters.pillow import PillowRasterSceneRenderer
from nonebot_plugin_htmlrender.adapters.resources import AnyioWorkerExecutor
from nonebot_plugin_htmlrender.adapters.skia import SkiaRasterSceneRenderer
from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    PixelRect,
    RasterBackendExecutionError,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)
from nonebot_plugin_htmlrender.graphics.execution import RasterWorkBudget
from nonebot_plugin_htmlrender.rendering import (
    OperationAdmissionGate,
    ProviderLifecycleError,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopOperationObserver

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot_plugin_htmlrender.rendering import RenderedImage
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.resources.ports import WorkerExecutor
    from tests.adapters.conftest import RecordingOperationObserver

R = TypeVar("R")


def _request(
    scene: RasterScene | None = None,
    output: RasterEncodeOptions | None = None,
) -> RenderRasterSceneRequest:
    return RenderRasterSceneRequest(
        scene if scene is not None else RasterScene(4, 3),
        output if output is not None else RasterEncodeOptions(),
    )


def _renderer(
    *,
    worker: WorkerExecutor | None = None,
    gate: OperationAdmissionGate | None = None,
    budget: RasterWorkBudget | None = None,
    observer: OperationObserver | None = None,
) -> PillowRasterSceneRenderer:
    return PillowRasterSceneRenderer(
        worker=worker if worker is not None else AnyioWorkerExecutor(),
        observer=observer if observer is not None else NoopOperationObserver(),
        operation_admission=gate if gate is not None else OperationAdmissionGate(),
        budget=(
            budget
            if budget is not None
            else RasterWorkBudget(max_pixels=1_000_000, max_concurrency=2)
        ),
    )


def _rgba_pixel(image: RenderedImage, x: int, y: int) -> tuple[int, int, int, int]:
    with Image.open(BytesIO(image.data)) as decoded:
        pixel = decoded.convert("RGBA").getpixel((x, y))
    assert isinstance(pixel, tuple) and len(pixel) == 4
    return pixel[0], pixel[1], pixel[2], pixel[3]


def _rgb_pixel(image: RenderedImage, x: int, y: int) -> tuple[int, int, int]:
    with Image.open(BytesIO(image.data)) as decoded:
        pixel = decoded.convert("RGB").getpixel((x, y))
    assert isinstance(pixel, tuple) and len(pixel) == 3
    return pixel[0], pixel[1], pixel[2]


def _assert_channels_close(
    actual: tuple[int, ...],
    expected: tuple[int, ...],
    *,
    tolerance: int,
) -> None:
    assert len(actual) == len(expected)
    assert all(
        abs(actual_channel - expected_channel) <= tolerance
        for actual_channel, expected_channel in zip(actual, expected, strict=True)
    ), (actual, expected)


class _BlockingThreadWorker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.thread_ident: int | None = None

    async def run_sync(self, function: Callable[..., R], *args: object) -> R:
        self.calls += 1

        def invoke() -> R:
            self.thread_ident = threading.get_ident()
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test worker was not released")
            return function(*args)

        return await run_sync_in_worker(invoke)


class _RecordingWorker:
    def __init__(self) -> None:
        self.calls = 0

    async def run_sync(self, function: Callable[..., R], *args: object) -> R:
        self.calls += 1
        return await run_sync_in_worker(function, *args)


class _NativeExplosion(Exception):
    pass


class _FailingWorker:
    async def run_sync(
        self,
        function: Callable[..., R],
        *args: object,
    ) -> R:
        del function, args
        raise _NativeExplosion("native allocation failed")


async def _wait_until_started(worker: _BlockingThreadWorker) -> None:
    started = await run_sync_in_worker(worker.started.wait, 2)
    assert started, "native worker did not start"


async def _wait_until_rejecting(gate: OperationAdmissionGate) -> None:
    with anyio.fail_after(2):
        while True:
            try:
                gate.ensure_accepting()
            except ProviderLifecycleError:
                return
            await checkpoint()


async def test_png_uses_physical_dimensions_and_half_open_clipping() -> None:
    scene = RasterScene(
        4,
        3,
        background=RGBAColor(3, 5, 7),
        commands=(
            FillRect(PixelRect(-1, 0, 3, 2), RGBAColor(255, 0, 0)),
            FillRect(PixelRect(3, 2, 2, 2), RGBAColor(0, 255, 0)),
            FillRect(PixelRect(9, 9, 1, 1), RGBAColor(0, 0, 255)),
        ),
    )

    result = await _renderer().render(_request(scene))

    assert (result.format, result.width, result.height) == ("png", 4, 3)
    assert _rgba_pixel(result, 0, 0) == (255, 0, 0, 255)
    assert _rgba_pixel(result, 1, 1) == (255, 0, 0, 255)
    assert _rgba_pixel(result, 2, 1) == (3, 5, 7, 255)
    assert _rgba_pixel(result, 3, 2) == (0, 255, 0, 255)


async def test_png_applies_source_over_without_replacing_destination() -> None:
    scene = RasterScene(
        2,
        2,
        background=RGBAColor(20, 40, 60, 128),
        commands=(FillRect(PixelRect(0, 0, 1, 1), RGBAColor(220, 100, 40, 128)),),
    )

    result = await _renderer().render(_request(scene))

    _assert_channels_close(
        _rgba_pixel(result, 0, 0),
        (153, 80, 47, 192),
        tolerance=1,
    )
    assert _rgba_pixel(result, 1, 1) == (20, 40, 60, 128)


async def test_jpeg_composites_the_complete_scene_over_the_matte() -> None:
    matte = RGBAColor(10, 60, 180)
    scene = RasterScene(
        48,
        24,
        commands=(FillRect(PixelRect(8, 4, 16, 16), RGBAColor(220, 100, 40, 128)),),
    )
    output = RasterEncodeOptions(format="jpeg", quality=100, matte=matte)

    result = await _renderer().render(_request(scene, output))

    assert (result.format, result.width, result.height) == ("jpeg", 48, 24)
    _assert_channels_close(_rgb_pixel(result, 0, 0), (10, 60, 180), tolerance=3)
    _assert_channels_close(_rgb_pixel(result, 12, 12), (115, 80, 110), tolerance=4)


async def test_native_rendering_is_delegated_without_blocking_the_event_loop() -> None:
    worker = _BlockingThreadWorker()
    renderer = _renderer(worker=worker)
    result: list[RenderedImage] = []
    render_finished = anyio.Event()
    heartbeat = anyio.Event()

    async def render() -> None:
        result.append(await renderer.render(_request()))
        render_finished.set()

    async def beat() -> None:
        await checkpoint()
        heartbeat.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await _wait_until_started(worker)
        try:
            task_group.start_soon(beat)
            await heartbeat.wait()
            assert not render_finished.is_set()
            assert worker.thread_ident != threading.get_ident()
        finally:
            worker.release.set()

    assert result[0].format == "png"


async def test_shared_budget_limits_pixels_before_worker_dispatch() -> None:
    worker = _RecordingWorker()
    renderer = _renderer(
        worker=worker,
        budget=RasterWorkBudget(max_pixels=3, max_concurrency=1),
    )

    with pytest.raises(InvalidRenderRequest, match="4 pixels"):
        await renderer.render(_request(RasterScene(2, 2)))

    assert worker.calls == 0


async def test_one_budget_serializes_pillow_and_skia_native_work() -> None:
    budget = RasterWorkBudget(max_pixels=100, max_concurrency=1)
    pillow_worker = _BlockingThreadWorker()
    skia_worker = _RecordingWorker()
    gate = OperationAdmissionGate()
    pillow = _renderer(worker=pillow_worker, gate=gate, budget=budget)
    skia_renderer = SkiaRasterSceneRenderer(
        worker=skia_worker,
        observer=NoopOperationObserver(),
        operation_admission=gate,
        budget=budget,
    )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(pillow.render, _request())
        await _wait_until_started(pillow_worker)
        try:
            task_group.start_soon(skia_renderer.render, _request())
            await wait_all_tasks_blocked()
            assert skia_worker.calls == 0
        finally:
            pillow_worker.release.set()

    assert skia_worker.calls == 1


async def test_native_failure_is_translated_to_stable_backend_error() -> None:
    renderer = _renderer(worker=_FailingWorker())

    with pytest.raises(RasterBackendExecutionError) as raised:
        await renderer.render(_request())

    assert raised.value.backend == "pillow"
    assert isinstance(raised.value.__cause__, _NativeExplosion)
    assert "native allocation failed" in str(raised.value)


async def test_observation_identifies_pillow_backend(
    operation_observer: RecordingOperationObserver,
) -> None:
    result = await _renderer(observer=operation_observer).render(_request())

    assert result.format == "png"
    assert operation_observer.operations == [
        (
            "graphics.pillow.render_scene",
            {"render.backend": "pillow", "render.format": "png"},
            "success",
        )
    ]


async def test_retained_renderer_is_rejected_after_gate_stops_and_inflight_drains() -> (
    None
):
    worker = _BlockingThreadWorker()
    gate = OperationAdmissionGate()
    renderer = _renderer(worker=worker, gate=gate)
    close_finished = anyio.Event()

    async def close() -> None:
        await gate.stop_accepting_and_drain()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(renderer.render, _request())
        await _wait_until_started(worker)
        try:
            task_group.start_soon(close)
            await _wait_until_rejecting(gate)
            assert not close_finished.is_set()

            with pytest.raises(ProviderLifecycleError, match="closing or closed"):
                await renderer.render(_request())
        finally:
            worker.release.set()

        await close_finished.wait()
