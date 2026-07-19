from __future__ import annotations

import anyio
from anyio import wait_all_tasks_blocked
import pytest

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.graphics.execution import RasterWorkBudget
from nonebot_plugin_htmlrender.graphics.models import (
    FillRect,
    PixelRect,
    RasterScene,
    RGBAColor,
)


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
