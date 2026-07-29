from __future__ import annotations

from typing import TYPE_CHECKING, ParamSpec, TypeVar

import anyio
from anyio import wait_all_tasks_blocked
import pytest

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.graphics.errors import RasterBackendExecutionError
from nonebot_plugin_htmlrender.graphics.execution import (
    RasterWorkBudget,
    run_raster_backend,
)
from nonebot_plugin_htmlrender.graphics.models import (
    FillRect,
    PixelRect,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)
from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
from tests.adapters.conftest import RecordingOperationObserver
from tests.image_fixtures import rendered_image

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot_plugin_htmlrender.rendering import RenderedImage

T = TypeVar("T")
P = ParamSpec("P")


class _InlineWorker:
    def __init__(self) -> None:
        self.calls = 0

    async def run_sync(
        self,
        function: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        self.calls += 1
        return function(*args, **kwargs)


async def test_budget_rejects_oversized_scene_before_reserving_work() -> None:
    budget = RasterWorkBudget(max_pixels=15, max_concurrency=1)

    with pytest.raises(InvalidRenderRequest, match="16 pixels"):
        async with budget.reserve(RasterScene(4, 4)):
            raise AssertionError("oversized scene entered the work slot")


async def test_budget_rejects_scene_with_too_many_draw_commands() -> None:
    budget = RasterWorkBudget(max_pixels=16, max_concurrency=1, max_commands=2)
    commands = tuple(
        FillRect(PixelRect(0, 0, 1, 1), RGBAColor(0, 0, 0, 255)) for _ in range(3)
    )
    scene = RasterScene(4, 4, commands=commands)

    with pytest.raises(InvalidRenderRequest, match="3 draw commands"):
        async with budget.reserve(scene):
            raise AssertionError("over-budget scene entered the work slot")


async def test_budget_is_shared_across_concurrent_scene_work() -> None:
    budget = RasterWorkBudget(max_pixels=16, max_concurrency=1)
    first_entered = anyio.Event()
    release_first = anyio.Event()
    second_entered = anyio.Event()

    async def first() -> None:
        async with budget.reserve(RasterScene(4, 4)):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        async with budget.reserve(RasterScene(1, 1)):
            second_entered.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(first)
        await first_entered.wait()
        task_group.start_soon(second)
        await wait_all_tasks_blocked()
        assert not second_entered.is_set()
        release_first.set()

    assert second_entered.is_set()
    assert budget.max_pixels == 16
    assert budget.max_concurrency == 1


async def test_run_raster_backend_owns_worker_and_observation_contract() -> None:
    request = RenderRasterSceneRequest(
        RasterScene(2, 3),
        RasterEncodeOptions(),
    )
    worker = _InlineWorker()
    observer = RecordingOperationObserver()

    result = await run_raster_backend(
        "pillow",
        request,
        lambda _: rendered_image(width=2, height=3),
        worker=worker,
        observer=observer,
        operation_admission=OperationAdmissionGate(),
        budget=RasterWorkBudget(max_pixels=6, max_concurrency=1),
    )

    assert (result.width, result.height) == (2, 3)
    assert worker.calls == 1
    assert observer.operations == [
        (
            "graphics.pillow.render_scene",
            {"render.backend": "pillow", "render.format": "png"},
            "success",
        )
    ]


async def test_run_raster_backend_translates_worker_failure() -> None:
    request = RenderRasterSceneRequest(RasterScene(1, 1), RasterEncodeOptions())

    def fail(_: RenderRasterSceneRequest) -> RenderedImage:
        raise RuntimeError("native failure")

    with pytest.raises(RasterBackendExecutionError) as raised:
        await run_raster_backend(
            "skia",
            request,
            fail,
            worker=_InlineWorker(),
            observer=RecordingOperationObserver(),
            operation_admission=OperationAdmissionGate(),
            budget=RasterWorkBudget(max_pixels=1, max_concurrency=1),
        )

    assert raised.value.backend == "skia"
    assert isinstance(raised.value.__cause__, RuntimeError)
