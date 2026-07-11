from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from typing import TYPE_CHECKING

import anyio
from anyio.to_thread import run_sync
import pytest

from nonebot_plugin_htmlrender.resources import (
    FilesystemResourceSource,
    PackageResourceSource,
    read_resource_text,
)
from nonebot_plugin_htmlrender.resources import budget as budget_module
from nonebot_plugin_htmlrender.resources.budget import ResourceCacheBudget
from nonebot_plugin_htmlrender.resources.cache import (
    FileResourceCache,
    FileRevision,
    FileSnapshot,
)
from nonebot_plugin_htmlrender.resources.source import (
    PackageResource,
    PackageResourceCache,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_resource_budget_exports_atomic_event_deltas(
    mocker: MockerFixture,
) -> None:
    export = mocker.patch.object(budget_module, "record_cache_metrics")
    budget = ResourceCacheBudget(max_entries=4, max_bytes=32)
    budget.record_hit()
    budget.record_miss()
    budget.record_load()
    budget.record_wait()

    budget.export_metrics()
    budget.export_metrics()

    assert export.call_args_list == [
        mocker.call(
            "resource",
            {"hit": 1, "miss": 1, "load": 1, "wait": 1, "eviction": 0},
            0,
            0,
        ),
        mocker.call(
            "resource",
            {"hit": 0, "miss": 0, "load": 0, "wait": 0, "eviction": 0},
            0,
            0,
        ),
    ]


def test_resource_sources_use_stable_identities_and_reject_traversal(
    tmp_path: Path,
) -> None:
    package = PackageResourceSource("nonebot_plugin_htmlrender", "templates")
    filesystem = FilesystemResourceSource(tmp_path)

    assert package.identity == (
        "package",
        "nonebot_plugin_htmlrender",
        "templates",
    )
    assert filesystem.identity == ("filesystem", str(tmp_path.resolve()))
    assert package.resource("text/text.html").name == "templates/text/text.html"
    assert filesystem.resource("text.css") == (tmp_path / "text.css").resolve()

    with pytest.raises(ValueError, match="Invalid logical resource"):
        package.resource("../secret")
    with pytest.raises(ValueError, match="Invalid logical resource"):
        filesystem.resource("../secret")


@pytest.mark.anyio
async def test_package_resource_reads_without_exposing_a_path() -> None:
    package = PackageResourceSource("nonebot_plugin_htmlrender", "templates")
    template = package.resource("text/text.html")

    rendered = await read_resource_text(template)

    assert "<head>" in rendered
    assert template.cache_key == (
        "package",
        "nonebot_plugin_htmlrender",
        "templates/text/text.html",
    )


@pytest.mark.anyio
async def test_package_cache_clear_prevents_old_inflight_writeback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = PackageResourceCache(max_entries=4, max_bytes=1024)
    resource = PackageResource("example_package", "resource.bin")
    captured_old = threading.Event()
    release_old = threading.Event()
    payload = b"old"
    calls = 0

    class Traversable:
        def read_bytes(self) -> bytes:
            nonlocal calls
            calls += 1
            captured = payload
            if calls == 1:
                captured_old.set()
                assert release_old.wait(timeout=2)
            return captured

    monkeypatch.setattr(PackageResource, "traversable", lambda _: Traversable())
    old_results: list[bytes] = []

    async def load_old() -> None:
        old_results.append(await cache.read_bytes(resource))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(load_old)
        assert await run_sync(captured_old.wait, 2)
        await cache.clear()
        payload = b"new"
        assert await cache.read_bytes(resource) == b"new"
        release_old.set()

    assert old_results == [b"old"]
    assert await cache.read_bytes(resource) == b"new"


@pytest.mark.anyio
async def test_package_and_filesystem_sources_share_one_weighted_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = ResourceCacheBudget(max_entries=1, max_bytes=4)
    filesystem_cache = FileResourceCache(
        max_entries=1,
        max_bytes=4,
        revalidate_seconds=60,
        budget=budget,
    )
    package_cache = PackageResourceCache(
        max_entries=1,
        max_bytes=4,
        budget=budget,
    )
    path = tmp_path / "file.bin"
    path.write_bytes(b"file")
    package_reads = 0

    class Traversable:
        def read_bytes(self) -> bytes:
            nonlocal package_reads
            package_reads += 1
            return b"pkg"

    monkeypatch.setattr(PackageResource, "traversable", lambda _: Traversable())
    resource = PackageResource("example_package", "resource.bin")

    assert await filesystem_cache.read_bytes(path) == b"file"
    assert await package_cache.read_bytes(resource) == b"pkg"

    stats = await filesystem_cache.stats()
    assert stats.entries == 1
    assert stats.resident_bytes == 3
    assert stats.loads == 2
    assert stats.evictions == 1

    assert await filesystem_cache.read_bytes(path) == b"file"
    assert (await filesystem_cache.stats()).evictions == 2
    assert package_reads == 1


def test_shared_budget_serializes_cross_participant_eviction(tmp_path: Path) -> None:
    budget = ResourceCacheBudget(max_entries=4, max_bytes=16)
    filesystem_cache = FileResourceCache(
        max_entries=4,
        max_bytes=16,
        revalidate_seconds=60,
        budget=budget,
    )
    package_cache = PackageResourceCache(
        max_entries=4,
        max_bytes=16,
        budget=budget,
    )
    revision = FileRevision(device=1, inode=1, size=4, mtime_ns=1, ctime_ns=1)

    def store_files(index: int) -> None:
        for offset in range(100):
            path = tmp_path / f"file-{index}-{offset}.bin"
            snapshot = FileSnapshot(path=path, revision=revision, data=b"file")
            with budget.locked():
                filesystem_cache._store(
                    snapshot,
                    checked_at=0,
                    epoch=0,
                    generation=0,
                )

    def store_packages(index: int) -> None:
        for offset in range(100):
            key = ("package", str(index), str(offset))
            with budget.locked():
                package_cache._store(key, b"pkg")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(store_files, 0),
            executor.submit(store_packages, 0),
            executor.submit(store_files, 1),
            executor.submit(store_packages, 1),
        ]
        for future in futures:
            future.result()

    stats = budget.stats()
    assert stats.entries <= 4
    assert stats.resident_bytes >= 0
    assert stats.resident_bytes == (
        filesystem_cache._resident_bytes + package_cache._resident_bytes
    )


@pytest.mark.anyio
async def test_shared_clear_invalidates_package_inflight_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = ResourceCacheBudget(max_entries=4, max_bytes=1024)
    filesystem_cache = FileResourceCache(
        max_entries=4,
        max_bytes=1024,
        revalidate_seconds=60,
        budget=budget,
    )
    package_cache = PackageResourceCache(
        max_entries=4,
        max_bytes=1024,
        budget=budget,
    )
    resource = PackageResource("example_package", "resource.bin")
    captured_old = threading.Event()
    release_old = threading.Event()
    payload = b"old"
    calls = 0

    class Traversable:
        def read_bytes(self) -> bytes:
            nonlocal calls
            calls += 1
            captured = payload
            if calls == 1:
                captured_old.set()
                assert release_old.wait(timeout=2)
            return captured

    monkeypatch.setattr(PackageResource, "traversable", lambda _: Traversable())
    old_results: list[bytes] = []

    async def load_old() -> None:
        old_results.append(await package_cache.read_bytes(resource))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(load_old)
        assert await run_sync(captured_old.wait, 2)
        await filesystem_cache.clear()
        payload = b"new"
        assert await package_cache.read_bytes(resource) == b"new"
        release_old.set()

    assert old_results == [b"old"]
    assert await package_cache.read_bytes(resource) == b"new"
    assert (await filesystem_cache.stats()).entries == 1
