from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import anyio
import pytest

from nonebot_plugin_htmlrender.backend.takumi import (
    TakumiConfig,
    TakumiImageResource,
    TakumiRuntimeError,
)
from nonebot_plugin_htmlrender.backend.takumi.runtime import TakumiRuntimeState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest import MonkeyPatch

    from nonebot_plugin_htmlrender.backend.takumi.types import NativeRenderer


class _ImageResource:
    def __init__(self, src: str, data: bytes, *, cache: str) -> None:
        self.src = src
        self.data = data
        self.cache = cache


@dataclass(frozen=True)
class _HtmlOptions:
    presets: str
    tailwind_property: str | None
    max_depth: int | None


class _FakeRenderer:
    def __init__(self) -> None:
        self.html_compiles = 0
        self.css_compiles = 0
        self.render_calls: list[dict[str, object]] = []

    def where(self) -> int:
        return threading.get_ident()

    def compile_html(self, html: str, **kwargs: object) -> object:
        self.html_compiles += 1
        return SimpleNamespace(node=(html, kwargs))

    def compile_stylesheet_lossy(self, css: str) -> object:
        self.css_compiles += 1
        return ("css", css)

    def render_compiled(self, node: object, **kwargs: object) -> bytes:
        self.render_calls.append({"node": node, **kwargs})
        return b"rendered"

    def render_node(self, node: object, **kwargs: object) -> bytes:
        self.render_calls.append(
            {"node": node, "thread": threading.get_ident(), **kwargs}
        )
        return b"node"


@pytest.fixture
def fake_takumi_module(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "takumi_py",
        SimpleNamespace(ImageResource=_ImageResource, HtmlOptions=_HtmlOptions),
    )


def _state(renderer: _FakeRenderer, *, cache_entries: int = 8) -> TakumiRuntimeState:
    return TakumiRuntimeState(
        renderer=cast("NativeRenderer", renderer),
        limiter=anyio.CapacityLimiter(2),
        config=TakumiConfig(compiled_cache_max_entries=cache_entries),
    )


@pytest.mark.anyio
async def test_native_calls_and_image_construction_run_in_worker(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer)
    event_loop_thread = threading.get_ident()

    worker_thread = await state.call_renderer("where")
    result = await state.call_renderer(
        "render_node",
        {"type": "container"},
        images=(TakumiImageResource("memory:image", b"payload"),),
    )

    assert result == b"node"
    assert worker_thread != event_loop_thread
    assert renderer.render_calls[-1]["thread"] != event_loop_thread
    images = cast("Sequence[object]", renderer.render_calls[-1]["images"])
    image = images[0]
    assert isinstance(image, _ImageResource)
    assert image.src == "memory:image"


@pytest.mark.anyio
async def test_document_compilation_is_reused_and_cache_can_be_disabled(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer)

    for _ in range(2):
        assert (
            await state.call_document(
                "render_compiled",
                "<div>same</div>",
                ("div { color: red }",),
                width=None,
                height=None,
            )
            == b"rendered"
        )
    assert renderer.html_compiles == 1
    assert renderer.css_compiles == 1

    uncached_renderer = _FakeRenderer()
    uncached = _state(uncached_renderer, cache_entries=0)
    for _ in range(2):
        await uncached.call_document(
            "render_compiled",
            "<div>same</div>",
            ("div { color: red }",),
        )
    assert uncached_renderer.html_compiles == 2
    assert uncached_renderer.css_compiles == 2


@pytest.mark.anyio
async def test_runtime_close_is_idempotent_and_blocks_future_calls() -> None:
    state = _state(_FakeRenderer())
    await state.aclose()
    await state.aclose()

    with pytest.raises(TakumiRuntimeError, match="closed"):
        await state.call_renderer("where")
