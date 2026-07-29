from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
import pytest

from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_html
from nonebot_plugin_htmlrender.rendering.budget import (
    BudgetedPreparedHtmlExecutor,
    HtmlRenderBudget,
)
from nonebot_plugin_htmlrender.rendering.errors import InvalidRenderRequest
from tests.image_fixtures import rendered_image

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy


class _Executor:
    def __init__(self, result: RenderedImage) -> None:
        self.result = result
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = anyio.Lock()

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> RenderedImage:
        del prepared, options, resource_policy, timeout_seconds
        async with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        await anyio.sleep(0.01)
        async with self._lock:
            self.active -= 1
        return self.result


def _executor(
    budget: HtmlRenderBudget,
    *,
    result: RenderedImage | None = None,
) -> tuple[BudgetedPreparedHtmlExecutor, _Executor]:
    inner = _Executor(result or rendered_image("png", width=2, height=2))
    return BudgetedPreparedHtmlExecutor(inner, budget), inner


@pytest.mark.anyio
async def test_html_budget_rejects_oversized_source_before_provider() -> None:
    executor, inner = _executor(HtmlRenderBudget(max_source_bytes=3))

    with pytest.raises(InvalidRenderRequest, match="source bytes"):
        await executor.execute(
            prepare_html("<p>large</p>"),
            RasterOptions(width=1, height=1, device_pixel_ratio=1),
        )

    assert inner.calls == 0


@pytest.mark.anyio
async def test_html_budget_rejects_explicit_physical_pixels_before_provider() -> None:
    executor, inner = _executor(HtmlRenderBudget(max_pixels=15))

    with pytest.raises(InvalidRenderRequest, match="16 physical pixels"):
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=2, height=2, device_pixel_ratio=2),
        )

    assert inner.calls == 0


@pytest.mark.anyio
async def test_html_budget_rejects_device_pixel_ratio_before_provider() -> None:
    executor, inner = _executor(HtmlRenderBudget(max_device_pixel_ratio=2))

    with pytest.raises(InvalidRenderRequest, match="device_pixel_ratio"):
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=1, height=None, device_pixel_ratio=3),
        )

    assert inner.calls == 0


@pytest.mark.anyio
async def test_html_budget_validates_content_driven_output() -> None:
    oversized = rendered_image("png", width=4, height=5)
    executor, inner = _executor(
        HtmlRenderBudget(max_pixels=19, max_auto_height=4),
        result=oversized,
    )

    with pytest.raises(InvalidRenderRequest, match="20 physical pixels"):
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=4, height=None, device_pixel_ratio=1),
        )

    assert inner.calls == 1


@pytest.mark.anyio
async def test_html_budget_validates_content_driven_height() -> None:
    tall = rendered_image("png", width=2, height=5)
    executor, _ = _executor(
        HtmlRenderBudget(max_pixels=100, max_auto_height=4),
        result=tall,
    )

    with pytest.raises(InvalidRenderRequest, match="height 5"):
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=2, height=None, device_pixel_ratio=1),
        )


@pytest.mark.anyio
async def test_html_budget_validates_encoded_output_size() -> None:
    result = rendered_image("png", width=1, height=1)
    executor, _ = _executor(
        HtmlRenderBudget(max_output_bytes=len(result.data) - 1),
        result=result,
    )

    with pytest.raises(InvalidRenderRequest, match="Rendered image contains"):
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=1, height=1, device_pixel_ratio=1),
        )


@pytest.mark.anyio
async def test_html_budget_concurrency_is_shared_across_callers() -> None:
    executor, inner = _executor(HtmlRenderBudget(max_concurrency=2))

    async def render() -> None:
        await executor.execute(
            prepare_html(""),
            RasterOptions(width=1, height=1, device_pixel_ratio=1),
        )

    async with anyio.create_task_group() as group:
        for _ in range(8):
            group.start_soon(render)

    assert inner.calls == 8
    assert inner.max_active == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_source_bytes", 0),
        ("max_pixels", 0),
        ("max_output_bytes", 0),
        ("max_device_pixel_ratio", 0),
        ("max_auto_height", 0),
        ("max_concurrency", 0),
    ],
)
def test_html_budget_rejects_invalid_limits(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        if field == "max_source_bytes":
            HtmlRenderBudget(max_source_bytes=value)
        elif field == "max_pixels":
            HtmlRenderBudget(max_pixels=value)
        elif field == "max_output_bytes":
            HtmlRenderBudget(max_output_bytes=value)
        elif field == "max_device_pixel_ratio":
            HtmlRenderBudget(max_device_pixel_ratio=value)
        elif field == "max_auto_height":
            HtmlRenderBudget(max_auto_height=value)
        else:
            HtmlRenderBudget(max_concurrency=value)
