from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import anyio
import jinja2
import pytest

from nonebot_plugin_htmlrender.resources import PackageResourceSource, templating

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def _clear_environment_cache() -> Iterator[None]:
    templating.clear_template_environment_cache()
    yield
    templating.clear_template_environment_cache()


def _write_template(root: Path, content: str, name: str = "card.html") -> None:
    root.mkdir()
    (root / name).write_text(content, encoding="utf-8")


@pytest.mark.anyio
async def test_package_loader_renders_builtin_template() -> None:
    source = PackageResourceSource(
        "nonebot_plugin_htmlrender",
        "templates/text",
    )

    rendered = await templating.render_template_html(
        source,
        "text.html",
        {"text": "package", "css": ""},
        immutable=True,
    )

    assert "package" in rendered
    assert templating.get_template_environment_cache_stats().entries == 1


@pytest.mark.anyio
async def test_render_template_reuses_environment_and_loads_off_thread(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    root = tmp_path / "templates"
    _write_template(root, "Hello {{ name }}")
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

    assert await templating.render_template_html(root, "card.html", {"name": "A"}) == (
        "Hello A"
    )
    assert await templating.render_template_html(root, "card.html", {"name": "B"}) == (
        "Hello B"
    )

    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 1
    assert stats.hits == 1
    assert stats.misses == 1
    assert loader_threads
    assert all(thread_id != caller_thread for thread_id in loader_threads)


@pytest.mark.anyio
async def test_filter_identity_separates_immutable_environments(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "{{ value|decorate }}")

    def first(value: str) -> str:
        return f"first:{value}"

    def second(value: str) -> str:
        return f"second:{value}"

    assert (
        await templating.render_template_html(
            root,
            "card.html",
            {"value": "x"},
            filters={"decorate": first},
            immutable=True,
        )
        == "first:x"
    )
    assert (
        await templating.render_template_html(
            root,
            "card.html",
            {"value": "x"},
            filters={"decorate": second},
            immutable=True,
        )
        == "second:x"
    )
    assert (
        await templating.render_template_html(
            root,
            "card.html",
            {"value": "y"},
            filters={"decorate": first},
            immutable=True,
        )
        == "first:y"
    )

    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 2
    assert stats.hits == 1
    assert stats.misses == 2


@pytest.mark.anyio
async def test_cache_key_includes_root_immutable_and_extensions(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_template(first_root, "first")
    _write_template(second_root, "second")

    assert await templating.render_template_html(first_root, "card.html", {}) == "first"
    assert (
        await templating.render_template_html(second_root, "card.html", {}) == "second"
    )
    assert (
        await templating.render_template_html(
            first_root, "card.html", {}, immutable=True
        )
        == "first"
    )
    assert (
        await templating.render_template_html(
            first_root,
            "card.html",
            {},
            extensions=("jinja2.ext.do",),
        )
        == "first"
    )

    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 4
    assert stats.misses == 4


@pytest.mark.anyio
async def test_environment_cache_is_bounded_lru(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch.object(templating, "_get_cache_max_entries", return_value=2)
    roots = [tmp_path / name for name in ("a", "b", "c")]
    for index, root in enumerate(roots):
        _write_template(root, str(index))

    assert await templating.render_template_html(roots[0], "card.html", {}) == "0"
    assert await templating.render_template_html(roots[1], "card.html", {}) == "1"
    assert await templating.render_template_html(roots[0], "card.html", {}) == "0"
    assert await templating.render_template_html(roots[2], "card.html", {}) == "2"

    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 2
    assert stats.max_entries == 2
    assert stats.hits == 1
    assert stats.misses == 3
    assert stats.evictions == 1

    assert await templating.render_template_html(roots[1], "card.html", {}) == "1"
    stats = templating.get_template_environment_cache_stats()
    assert stats.misses == 4
    assert stats.evictions == 2


@pytest.mark.anyio
async def test_zero_capacity_disables_environment_cache(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch.object(templating, "_get_cache_max_entries", return_value=0)
    root = tmp_path / "templates"
    _write_template(root, "value")

    assert await templating.render_template_html(root, "card.html", {}) == "value"
    assert await templating.render_template_html(root, "card.html", {}) == "value"

    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 0
    assert stats.max_entries == 0
    assert stats.hits == 0
    assert stats.misses == 2
    assert stats.evictions == 0


@pytest.mark.anyio
async def test_immutable_template_reload_requires_invalidation(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "v1")

    assert (
        await templating.render_template_html(root, "card.html", {}, immutable=True)
        == "v1"
    )
    (root / "card.html").write_text("v2", encoding="utf-8")
    assert (
        await templating.render_template_html(root, "card.html", {}, immutable=True)
        == "v1"
    )

    assert templating.invalidate_template_environment_cache(root) == 1
    assert (
        await templating.render_template_html(root, "card.html", {}, immutable=True)
        == "v2"
    )


@pytest.mark.anyio
async def test_render_async_remains_concurrent(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    _write_template(root, "{{ value|observe }}")
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
        rendered = await templating.render_template_html(
            root,
            "card.html",
            {"value": str(index)},
            filters={"observe": observe},
        )
        results.append(rendered)

    async with anyio.create_task_group() as task_group:
        for index in range(8):
            task_group.start_soon(render, index)

    assert sorted(results) == [str(index) for index in range(8)]
    assert max_active > 1
    stats = templating.get_template_environment_cache_stats()
    assert stats.entries == 1
    assert stats.misses == 1
    assert stats.hits == 7


def test_clear_cache_resets_entries_and_statistics(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch.object(templating, "_get_cache_max_entries", return_value=2)
    root = tmp_path / "templates"
    _write_template(root, "unused")
    entry = templating._get_environment_entry(
        root.resolve(),
        immutable=False,
        extensions=(),
        filters=(),
    )
    assert isinstance(entry.environment, jinja2.Environment)
    assert templating.get_template_environment_cache_stats().entries == 1

    templating.clear_template_environment_cache()

    assert templating.get_template_environment_cache_stats() == (
        templating.TemplateEnvironmentCacheStats(
            entries=0,
            max_entries=2,
            hits=0,
            misses=0,
            evictions=0,
        )
    )


def test_template_cache_exports_hit_miss_and_current_entries(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    export = mocker.patch.object(templating, "record_cache_metrics")
    root = tmp_path / "templates"
    _write_template(root, "unused")

    templating._get_environment_entry(
        root,
        immutable=False,
        extensions=(),
        filters=(),
    )
    templating._get_environment_entry(
        root,
        immutable=False,
        extensions=(),
        filters=(),
    )

    assert export.call_args_list == [
        mocker.call("template_environment", {"miss": 1, "eviction": 0}, 1),
        mocker.call("template_environment", {"hit": 1, "eviction": 0}, 1),
    ]
