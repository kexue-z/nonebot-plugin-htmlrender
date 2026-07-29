from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import anyio
import jinja2
import pytest

from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
)
from nonebot_plugin_htmlrender.adapters.templates import JinjaTemplateCompiler
from nonebot_plugin_htmlrender.resources.errors import ResourceAccessDenied
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.source import PackageResourceSource
from nonebot_plugin_htmlrender.resources.templating import (
    TemplateEnvironmentCacheStats,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from tests.resources.conftest import (
        FailingCacheObserver,
        RecordingCacheObserver,
    )


def _write_template(root: Path, content: str, name: str = "card.html") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")


def _compiler(
    *,
    max_entries: int,
    observer: NoopCacheObserver | RecordingCacheObserver | FailingCacheObserver,
) -> JinjaTemplateCompiler:
    return JinjaTemplateCompiler(
        max_entries=max_entries,
        observer=observer,
        worker=AnyioWorkerExecutor(),
        local_access=ConfiguredLocalAccessPolicy(allowed_roots=(), allow_any=True),
    )


@pytest.mark.anyio
async def test_package_loader_renders_builtin_template() -> None:
    compiler = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )
    source = PackageResourceSource(
        "nonebot_plugin_htmlrender",
        "templates/text",
    )

    rendered = await compiler.render(
        source,
        "text.html",
        {"text": "package", "css": ""},
        immutable=True,
    )

    assert "package" in rendered
    assert compiler.stats().entries == 1


@pytest.mark.anyio
async def test_render_reuses_environment_and_loads_off_thread(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    root = tmp_path / "templates"
    _write_template(root, "Hello {{ name }}")
    compiler = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )
    caller_thread = threading.get_ident()
    loader_threads: list[int] = []
    original_get_template = jinja2.Environment.get_template

    def tracked_get_template(
        environment: jinja2.Environment,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> jinja2.Template:
        loader_threads.append(threading.get_ident())
        return original_get_template(environment, name, *args, **kwargs)

    mocker.patch.object(jinja2.Environment, "get_template", tracked_get_template)

    assert await compiler.render(root, "card.html", {"name": "A"}) == "Hello A"
    assert await compiler.render(root, "card.html", {"name": "B"}) == "Hello B"

    assert compiler.stats() == TemplateEnvironmentCacheStats(
        entries=1,
        max_entries=4,
        hits=1,
        misses=1,
        evictions=0,
    )
    assert loader_threads
    assert all(thread_id != caller_thread for thread_id in loader_threads)


@pytest.mark.anyio
async def test_filesystem_loader_uses_injected_local_access_policy(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    _write_template(outside, "secret")
    compiler = JinjaTemplateCompiler(
        max_entries=1,
        observer=NoopCacheObserver(),
        worker=AnyioWorkerExecutor(),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(allowed,),
            allow_any=False,
        ),
    )

    with pytest.raises(ResourceAccessDenied, match="outside allowed roots"):
        await compiler.render(outside, "card.html", {})


@pytest.mark.anyio
async def test_filter_identity_is_part_of_the_environment_key(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "{{ value|decorate }}")
    compiler = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )

    def first(value: str) -> str:
        return f"first:{value}"

    def second(value: str) -> str:
        return f"second:{value}"

    assert (
        await compiler.render(
            root,
            "card.html",
            {"value": "x"},
            filters={"decorate": first},
            immutable=True,
        )
        == "first:x"
    )
    assert (
        await compiler.render(
            root,
            "card.html",
            {"value": "x"},
            filters={"decorate": second},
            immutable=True,
        )
        == "second:x"
    )
    assert (
        await compiler.render(
            root,
            "card.html",
            {"value": "y"},
            filters={"decorate": first},
            immutable=True,
        )
        == "first:y"
    )

    stats = compiler.stats()
    assert stats.entries == 2
    assert stats.hits == 1
    assert stats.misses == 2


@pytest.mark.anyio
async def test_cache_key_includes_source_mode_and_extensions(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_template(first_root, "first")
    _write_template(second_root, "second")
    compiler = _compiler(
        max_entries=8,
        observer=NoopCacheObserver(),
    )

    assert await compiler.render(first_root, "card.html", {}) == "first"
    assert await compiler.render(second_root, "card.html", {}) == "second"
    assert (
        await compiler.render(
            first_root,
            "card.html",
            {},
            immutable=True,
        )
        == "first"
    )
    assert (
        await compiler.render(
            first_root,
            "card.html",
            {},
            extensions=("jinja2.ext.do",),
        )
        == "first"
    )

    assert compiler.stats().entries == 4
    assert compiler.stats().misses == 4


@pytest.mark.anyio
async def test_environment_cache_is_bounded_lru(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("a", "b", "c")]
    for index, root in enumerate(roots):
        _write_template(root, str(index))
    compiler = _compiler(
        max_entries=2,
        observer=NoopCacheObserver(),
    )

    assert await compiler.render(roots[0], "card.html", {}) == "0"
    assert await compiler.render(roots[1], "card.html", {}) == "1"
    assert await compiler.render(roots[0], "card.html", {}) == "0"
    assert await compiler.render(roots[2], "card.html", {}) == "2"

    assert compiler.stats() == TemplateEnvironmentCacheStats(
        entries=2,
        max_entries=2,
        hits=1,
        misses=3,
        evictions=1,
    )
    assert await compiler.render(roots[1], "card.html", {}) == "1"
    assert compiler.stats().misses == 4
    assert compiler.stats().evictions == 2


@pytest.mark.anyio
async def test_zero_capacity_disables_environment_residency(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "value")
    compiler = _compiler(
        max_entries=0,
        observer=NoopCacheObserver(),
    )

    assert await compiler.render(root, "card.html", {}) == "value"
    assert await compiler.render(root, "card.html", {}) == "value"
    assert compiler.stats() == TemplateEnvironmentCacheStats(
        entries=0,
        max_entries=0,
        hits=0,
        misses=2,
        evictions=0,
    )


@pytest.mark.anyio
async def test_immutable_reload_requires_instance_invalidation(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "v1")
    compiler = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )
    other = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )

    assert await compiler.render(root, "card.html", {}, immutable=True) == "v1"
    assert await other.render(root, "card.html", {}, immutable=True) == "v1"
    (root / "card.html").write_text("v2", encoding="utf-8")
    assert await compiler.render(root, "card.html", {}, immutable=True) == "v1"

    assert compiler.invalidate(root) == 1
    assert compiler.invalidate(root) == 0
    assert await compiler.render(root, "card.html", {}, immutable=True) == "v2"
    assert await other.render(root, "card.html", {}, immutable=True) == "v1"


@pytest.mark.anyio
async def test_async_template_filters_remain_concurrent(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "{{ value|observe }}")
    compiler = _compiler(
        max_entries=4,
        observer=NoopCacheObserver(),
    )
    active = 0
    max_active = 0
    results: list[str] = []
    state_lock = anyio.Lock()

    async def observe(value: str) -> str:
        nonlocal active, max_active
        async with state_lock:
            active += 1
            max_active = max(max_active, active)
        await anyio.sleep(0.01)
        async with state_lock:
            active -= 1
        return value

    async def render(index: int) -> None:
        rendered = await compiler.render(
            root,
            "card.html",
            {"value": str(index)},
            filters={"observe": observe},
        )
        results.append(rendered)

    async with anyio.create_task_group() as group:
        for index in range(8):
            group.start_soon(render, index)

    assert sorted(results) == [str(index) for index in range(8)]
    assert max_active > 1
    assert compiler.stats().entries == 1
    assert compiler.stats().misses == 1
    assert compiler.stats().hits == 7


@pytest.mark.anyio
async def test_clear_resets_only_the_target_compiler(
    tmp_path: Path,
    recording_observer: RecordingCacheObserver,
) -> None:
    root = tmp_path / "templates"
    _write_template(root, "value")
    compiler = _compiler(
        max_entries=2,
        observer=recording_observer,
    )
    other = _compiler(
        max_entries=2,
        observer=NoopCacheObserver(),
    )

    await compiler.render(root, "card.html", {})
    await compiler.render(root, "card.html", {})
    await other.render(root, "card.html", {})
    await compiler.clear()

    assert compiler.stats() == TemplateEnvironmentCacheStats(
        entries=0,
        max_entries=2,
        hits=0,
        misses=0,
        evictions=0,
    )
    assert other.stats().entries == 1
    assert recording_observer.calls[-3:] == [
        ("template_environment", {"miss": 1}, 1, None),
        ("template_environment", {"hit": 1}, 1, None),
        ("template_environment", {}, 0, None),
    ]


@pytest.mark.anyio
async def test_compiler_survives_failing_observer(
    tmp_path: Path,
    failing_observer: FailingCacheObserver,
) -> None:
    root = tmp_path / "templates"
    _write_template(root, "value")
    compiler = _compiler(
        max_entries=2,
        observer=failing_observer,
    )

    assert await compiler.render(root, "card.html", {}) == "value"
    assert await compiler.render(root, "card.html", {}) == "value"


def test_compiler_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        _compiler(
            max_entries=-1,
            observer=NoopCacheObserver(),
        )
