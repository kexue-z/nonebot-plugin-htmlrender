from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from time import monotonic, sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import anyio
from anyio.to_thread import run_sync as run_sync_in_worker
import pytest

from nonebot_plugin_htmlrender.backend.takumi import (
    TakumiBackendError,
    TakumiConfig,
    TakumiFontConfig,
    TakumiImageResource,
    TakumiInputError,
    TakumiRuntimeError,
)
from nonebot_plugin_htmlrender.backend.takumi import runtime as takumi_runtime
from nonebot_plugin_htmlrender.backend.takumi.runtime import TakumiRuntimeState
from nonebot_plugin_htmlrender.resources import FileCachePolicy

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pytest import MonkeyPatch
    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.backend.takumi.types import NativeRenderer


def _wait_until(condition: Callable[[], bool], *, timeout: float = 2) -> None:
    deadline = monotonic() + timeout
    while not condition():
        if monotonic() >= deadline:
            raise TimeoutError("condition was not reached before the test deadline")
        sleep(0.001)


class _ImageResource:
    def __init__(self, src: str, data: bytes, *, cache: str) -> None:
        self.src = src
        self.data = data
        self.cache = cache
        self.constructed_on = threading.get_ident()


@dataclass(frozen=True)
class _FontResource:
    data: bytes
    name: str | None = None
    weight: float | None = None
    style: str | None = None
    subset_of: str | None = None
    generic_family: str | None = None


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
        self.font_registrations: list[object] = []

    def where(self) -> int:
        return threading.get_ident()

    def compile_html(self, html: str, **kwargs: object) -> object:
        self.html_compiles += 1
        return SimpleNamespace(node=(html, kwargs))

    def compile_stylesheet_lossy(self, css: str) -> object:
        self.css_compiles += 1
        return ("css", css)

    def compile_stylesheet(self, css: str) -> object:
        self.css_compiles += 1
        return ("strict-css", css)

    def render_compiled(self, node: object, **kwargs: object) -> bytes:
        self.render_calls.append({"node": node, **kwargs})
        return b"rendered"

    def render_node(self, node: object, **kwargs: object) -> bytes:
        self.render_calls.append(
            {"node": node, "thread": threading.get_ident(), **kwargs}
        )
        return b"node"

    def register_font(self, font: object) -> tuple[str, ...]:
        self.font_registrations.append(font)
        return (getattr(font, "name", None) or "Detected",)


@pytest.fixture
def fake_takumi_module(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "takumi_py",
        SimpleNamespace(
            FontResource=_FontResource,
            ImageResource=_ImageResource,
            HtmlOptions=_HtmlOptions,
        ),
    )


def _state(
    renderer: _FakeRenderer,
    *,
    cache_entries: int = 8,
    cache_bytes: int = 32 * 1024 * 1024,
) -> TakumiRuntimeState:
    return TakumiRuntimeState(
        renderer=cast("NativeRenderer", renderer),
        limiter=anyio.CapacityLimiter(2),
        config=TakumiConfig(
            compiled_cache_max_entries=cache_entries,
            compiled_cache_max_bytes=cache_bytes,
        ),
    )


def test_compiled_cache_defaults_and_stats_surface_are_read_only() -> None:
    config = TakumiConfig()
    state = _state(_FakeRenderer())

    assert config.compiled_cache_max_bytes == 32 * 1024 * 1024
    assert state.compiled_cache_stats.entries == 0
    assert TakumiRuntimeState.compiled_cache_stats.fset is None


@pytest.mark.anyio
async def test_native_calls_and_image_construction_run_in_worker(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer)
    event_loop_thread = threading.get_ident()

    worker_thread = await state.call_renderer("where")
    upstream = _ImageResource("upstream", b"upstream", cache="none")

    @dataclass(frozen=True)
    class PromisedImage:
        src: str
        data: bytes

    result = await state.call_renderer(
        "render_node",
        {"type": "container"},
        images=(
            TakumiImageResource("memory:image", b"payload"),
            upstream,
            ("tuple", b"tuple"),
            PromisedImage("duck", b"duck"),
        ),
    )

    assert result == b"node"
    assert worker_thread != event_loop_thread
    assert renderer.render_calls[-1]["thread"] != event_loop_thread
    images = cast("Sequence[_ImageResource]", renderer.render_calls[-1]["images"])
    assert all(isinstance(image, _ImageResource) for image in images)
    assert [(image.src, image.data, image.cache) for image in images] == [
        ("memory:image", b"payload", "auto"),
        ("upstream", b"upstream", "none"),
        ("tuple", b"tuple", "auto"),
        ("duck", b"duck", "auto"),
    ]
    assert all(image.constructed_on != event_loop_thread for image in images)


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


@pytest.mark.anyio
async def test_compiled_cache_enforces_entry_lru_and_weight_oversize(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer, cache_entries=2)

    for html in ("<p>A</p>", "<p>B</p>", "<p>A</p>", "<p>C</p>", "<p>B</p>"):
        await state.call_document("render_compiled", html, ())

    stats = state.compiled_cache_stats
    assert renderer.html_compiles == 4
    assert stats.entries == 2
    assert stats.hits == 1
    assert stats.evictions == 2

    oversized_renderer = _FakeRenderer()
    oversized = _state(oversized_renderer, cache_entries=8, cache_bytes=8)
    for _ in range(2):
        await oversized.call_document(
            "render_compiled",
            "<div>oversized</div>",
            (),
        )
    oversized_stats = oversized.compiled_cache_stats
    assert oversized_renderer.html_compiles == 2
    assert oversized_stats.entries == 0
    assert oversized_stats.resident_weight == 0
    assert oversized_stats.loads == 2


@pytest.mark.anyio
async def test_explicit_stylesheet_compilation_uses_shared_cache() -> None:
    renderer = _FakeRenderer()
    state = _state(renderer)

    strict_first = await state.compile_stylesheet("div { color: red }", lossy=False)
    strict_second = await state.compile_stylesheet("div { color: red }", lossy=False)
    lossy = await state.compile_stylesheet("div { color: red }", lossy=True)

    assert strict_first is strict_second
    assert strict_first != lossy
    assert renderer.css_compiles == 2
    assert state.compiled_cache_stats.hits == 1


@pytest.mark.anyio
async def test_compiled_cache_singleflights_same_key(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module

    class BlockingRenderer(_FakeRenderer):
        def __init__(self) -> None:
            super().__init__()
            self.compile_started = threading.Event()
            self.compile_release = threading.Event()

        def compile_html(self, html: str, **kwargs: object) -> object:
            self.html_compiles += 1
            self.compile_started.set()
            if not self.compile_release.wait(timeout=5):
                raise TimeoutError("test did not release compilation")
            return SimpleNamespace(node=(html, kwargs))

    renderer = BlockingRenderer()
    state = _state(renderer)
    results: list[object] = []

    async def render() -> None:
        results.append(await state.call_document("render_compiled", "<p>same</p>", ()))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await run_sync_in_worker(renderer.compile_started.wait)
        task_group.start_soon(render)
        await run_sync_in_worker(
            _wait_until,
            lambda: state.compiled_cache_stats.waits >= 1,
        )
        renderer.compile_release.set()

    assert results == [b"rendered", b"rendered"]
    assert renderer.html_compiles == 1
    assert state.compiled_cache_stats.loads == 1


@pytest.mark.anyio
async def test_compiled_cache_shares_errors_and_allows_retry(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module

    class FailingRenderer(_FakeRenderer):
        def __init__(self) -> None:
            super().__init__()
            self.compile_started = threading.Event()
            self.compile_release = threading.Event()
            self.fail = True

        def compile_html(self, html: str, **kwargs: object) -> object:
            self.html_compiles += 1
            self.compile_started.set()
            if not self.compile_release.wait(timeout=5):
                raise TimeoutError("test did not release compilation")
            if self.fail:
                raise RuntimeError("compile failed")
            return SimpleNamespace(node=(html, kwargs))

    renderer = FailingRenderer()
    state = _state(renderer)
    errors: list[RuntimeError] = []

    async def render() -> None:
        try:
            await state.call_document("render_compiled", "<p>same</p>", ())
        except RuntimeError as error:
            errors.append(error)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await run_sync_in_worker(renderer.compile_started.wait)
        task_group.start_soon(render)
        await run_sync_in_worker(
            _wait_until,
            lambda: state.compiled_cache_stats.waits >= 1,
        )
        renderer.compile_release.set()

    assert len(errors) == 2
    assert errors[0] is errors[1]
    assert renderer.html_compiles == 1

    renderer.fail = False
    assert (
        await state.call_document("render_compiled", "<p>same</p>", ()) == b"rendered"
    )
    assert renderer.html_compiles == 2


@pytest.mark.anyio
async def test_native_string_validation_reports_nested_field_before_call() -> None:
    renderer = _FakeRenderer()
    state = _state(renderer)

    with pytest.raises(TakumiInputError) as exc_info:
        await state.call_renderer(
            "render_node",
            {"type": "text", "text": "\ud800"},
        )

    assert exc_info.value.field == "render_node.args[0]['text']"
    assert renderer.render_calls == []


@pytest.mark.anyio
async def test_native_string_validation_covers_sets_and_rejects_iterators() -> None:
    renderer = _FakeRenderer()
    state = _state(renderer)

    with pytest.raises(TakumiInputError) as set_error:
        await state.call_renderer("render_node", {"values": {"\ud800"}})
    assert set_error.value.field.startswith("render_node.args[0]['values'][")

    with pytest.raises(TakumiInputError, match="one-shot iterator"):
        await state.call_renderer(
            "render_node",
            {"values": (value for value in ("safe",))},
        )


@pytest.mark.anyio
async def test_native_errors_are_translated_to_backend_error(
    fake_takumi_module: None,
    monkeypatch: MonkeyPatch,
) -> None:
    del fake_takumi_module

    class NativeError(Exception):
        pass

    module = sys.modules["takumi_py"]
    monkeypatch.setattr(module, "TakumiError", NativeError, raising=False)

    class FailingRenderer(_FakeRenderer):
        def where(self) -> int:
            raise NativeError("native failure")

    with pytest.raises(TakumiBackendError, match="native failure") as exc_info:
        await _state(FailingRenderer()).call_renderer("where")
    assert isinstance(exc_info.value.__cause__, NativeError)


@pytest.mark.anyio
async def test_panic_exception_is_translated_to_backend_error(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    panic_type = type(
        "PanicException",
        (BaseException,),
        {"__module__": "pyo3_runtime"},
    )

    class PanickingRenderer(_FakeRenderer):
        def where(self) -> int:
            raise panic_type("panic")

    with pytest.raises(TakumiBackendError, match="panic") as exc_info:
        await _state(PanickingRenderer()).call_renderer("where")
    assert isinstance(exc_info.value.__cause__, panic_type)


@pytest.mark.anyio
async def test_non_owner_close_wait_is_bounded(
    monkeypatch: MonkeyPatch,
) -> None:
    state = _state(_FakeRenderer())
    with state._lifecycle_lock:
        state._lifecycle = "closing"
    monkeypatch.setattr(takumi_runtime, "_CLOSE_WAIT_TIMEOUT", 0.02)

    with pytest.raises(TakumiRuntimeError, match="Timed out"):
        await state.aclose()


@pytest.mark.anyio
async def test_identifier_fields_reject_nul_before_native_call() -> None:
    renderer = _FakeRenderer()
    state = _state(renderer)

    with pytest.raises(TakumiInputError, match="NUL"):
        await state.call_renderer(
            "render_node",
            {"type": "container"},
            lang="en\0ignored",
        )
    with pytest.raises(TakumiInputError, match="NUL"):
        await state.call_renderer("render_node", {"type\0ignored": "container"})
    assert renderer.render_calls == []


def test_font_duck_type_does_not_mask_property_errors() -> None:
    class BrokenFont:
        @property
        def data(self) -> bytes:
            raise KeyError("broken property")

    with pytest.raises(KeyError, match="broken property"):
        takumi_runtime._coerce_font_spec(BrokenFont(), field_name="font")


@pytest.mark.anyio
async def test_font_file_cache_defaults_and_per_font_override(
    mocker: MockerFixture,
) -> None:
    assert TakumiConfig().font_cache_policy is FileCachePolicy.REVALIDATE
    config = TakumiConfig(
        fonts=[
            TakumiFontConfig(path=Path("default.ttf")),
            TakumiFontConfig(
                path=Path("immutable.ttf"),
                cache_policy=FileCachePolicy.IMMUTABLE,
            ),
        ]
    )
    read = mocker.patch.object(
        takumi_runtime,
        "read_resource_bytes",
        new=mocker.AsyncMock(return_value=b"font"),
    )

    payloads = await takumi_runtime._load_font_payloads(config.fonts, config=config)

    assert payloads == (b"font", b"font")
    policies = {call.kwargs["policy"] for call in read.await_args_list}
    assert policies == {FileCachePolicy.REVALIDATE, FileCachePolicy.IMMUTABLE}


@pytest.mark.anyio
async def test_dynamic_fonts_are_idempotent_and_changed_content_requires_rebuild(
    fake_takumi_module: None,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer)
    font_path = tmp_path / "font.ttf"
    read = mocker.patch.object(
        takumi_runtime,
        "read_resource_bytes",
        new=mocker.AsyncMock(side_effect=[b"same", b"same", b"changed"]),
    )

    first = await state.register_font_file(
        font_path,
        name="Configured",
        cache_policy=FileCachePolicy.REVALIDATE,
    )
    second = await state.register_font_file(
        font_path,
        name="Configured",
        cache_policy=FileCachePolicy.REVALIDATE,
    )

    assert first == second == ("Configured",)
    assert len(renderer.font_registrations) == 1
    with pytest.raises(TakumiRuntimeError, match="create a new runtime"):
        await state.register_font_file(
            font_path,
            name="Configured",
            cache_policy=FileCachePolicy.REVALIDATE,
        )
    assert len(renderer.font_registrations) == 1
    assert read.await_count == 3


@pytest.mark.anyio
async def test_dynamic_font_strings_are_validated_before_native_registration(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module
    renderer = _FakeRenderer()
    state = _state(renderer)

    with pytest.raises(TakumiInputError) as exc_info:
        await state.register_font(
            _FontResource(b"font", name="\ud800"),
            source="memory:font",
        )

    assert exc_info.value.field == "font.name"
    assert renderer.font_registrations == []


@pytest.mark.anyio
async def test_close_rejects_new_calls_waits_for_workers_and_clears_state(
    fake_takumi_module: None,
) -> None:
    del fake_takumi_module

    class BlockingRenderer(_FakeRenderer):
        def __init__(self) -> None:
            super().__init__()
            self.render_started = threading.Event()
            self.render_release = threading.Event()

        def render_node(self, node: object, **kwargs: object) -> bytes:
            self.render_started.set()
            if not self.render_release.wait(timeout=5):
                raise TimeoutError("test did not release rendering")
            return super().render_node(node, **kwargs)

    renderer = BlockingRenderer()
    state = _state(renderer)
    state.registered_font_families = ("Configured",)
    await state.call_document("render_compiled", "<p>cached</p>", ())
    assert state.compiled_cache_stats.entries == 1
    result: list[object] = []
    close_finished = anyio.Event()

    async def render() -> None:
        result.append(await state.call_renderer("render_node", {"type": "container"}))

    async def close() -> None:
        await state.aclose()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        await run_sync_in_worker(renderer.render_started.wait)
        task_group.start_soon(close)
        await run_sync_in_worker(_wait_until, lambda: state.closing)
        with pytest.raises(TakumiRuntimeError, match="closing"):
            await state.call_renderer("where")
        assert state.renderer is renderer
        assert not close_finished.is_set()
        renderer.render_release.set()

    assert result == [b"node"]
    assert close_finished.is_set()
    assert state.closed
    assert state.renderer is None
    assert state.compiled_cache_stats.entries == 0
    assert state.compiled_cache_stats.resident_weight == 0
    assert state.registered_font_families == ()
    await state.aclose()
