from __future__ import annotations

import time
from typing import TYPE_CHECKING

import anyio
import pytest

from nonebot_plugin_htmlrender.resources import cache as cache_module
from nonebot_plugin_htmlrender.resources.cache import (
    FileCachePolicy,
    FileResourceCache,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def _cache(
    *,
    max_entries: int = 8,
    max_bytes: int = 1024,
    revalidate_seconds: float = 60.0,
) -> FileResourceCache:
    return FileResourceCache(
        max_entries=max_entries,
        max_bytes=max_bytes,
        revalidate_seconds=revalidate_seconds,
    )


@pytest.mark.anyio
async def test_bytes_and_text_share_one_file_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "resource.txt"
    path.write_text("你好, Takumi", encoding="utf-8")
    cache = _cache()

    assert (
        await cache.read_bytes(path, policy=FileCachePolicy.IMMUTABLE)
        == path.read_bytes()
    )
    assert (
        await cache.read_text(path, policy=FileCachePolicy.IMMUTABLE) == "你好, Takumi"
    )

    stats = await cache.stats()
    assert stats.loads == 1
    assert stats.hits == 1
    assert stats.entries == 1


@pytest.mark.anyio
async def test_revalidate_refreshes_changed_file(tmp_path: Path) -> None:
    path = tmp_path / "resource.txt"
    path.write_text("first", encoding="utf-8")
    cache = _cache(revalidate_seconds=0)

    assert await cache.read_text(path) == "first"
    path.write_text("second", encoding="utf-8")
    assert await cache.read_text(path) == "second"
    assert (await cache.stats()).loads == 2


@pytest.mark.anyio
async def test_refresh_forces_a_new_read(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    path = tmp_path / "resource.bin"
    path.write_bytes(b"same")
    cache = _cache()
    read_spy = mocker.spy(cache_module, "_read_consistent_snapshot")

    await cache.read_bytes(path)
    await cache.read_bytes(path, refresh=True)

    assert read_spy.call_count == 2


@pytest.mark.anyio
async def test_concurrent_cold_reads_are_singleflight(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    path = tmp_path / "resource.bin"
    path.write_bytes(b"payload")
    cache = _cache()
    original = cache_module._read_consistent_snapshot
    calls = 0

    def slow_read(resource_path: Path):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return original(resource_path)

    mocker.patch.object(
        cache_module, "_read_consistent_snapshot", side_effect=slow_read
    )
    results: list[bytes] = []

    async def read() -> None:
        results.append(await cache.read_bytes(path))

    async with anyio.create_task_group() as task_group:
        for _ in range(12):
            task_group.start_soon(read)

    assert results == [b"payload"] * 12
    assert calls == 1
    assert (await cache.stats()).waits == 11


@pytest.mark.anyio
async def test_lru_obeys_entry_and_byte_limits(tmp_path: Path) -> None:
    paths = [tmp_path / f"{index}.bin" for index in range(3)]
    for path in paths:
        path.write_bytes(b"1234")
    cache = _cache(max_entries=2, max_bytes=8)

    for path in paths:
        await cache.read_bytes(path)

    stats = await cache.stats()
    assert stats.entries == 2
    assert stats.resident_bytes == 8
    assert stats.evictions == 1


@pytest.mark.anyio
async def test_oversized_value_bypasses_resident_cache(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"12345")
    cache = _cache(max_bytes=4)

    assert await cache.read_bytes(path) == b"12345"
    assert (await cache.stats()).entries == 0


@pytest.mark.anyio
async def test_invalidate_and_clear_release_entries(tmp_path: Path) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    cache = _cache()

    await cache.read_bytes(first)
    await cache.read_bytes(second)
    await cache.invalidate(first)
    assert (await cache.stats()).entries == 1
    await cache.clear()
    assert (await cache.stats()).entries == 0


@pytest.mark.anyio
async def test_load_errors_are_not_cached(tmp_path: Path) -> None:
    path = tmp_path / "late.bin"
    cache = _cache()

    with pytest.raises(FileNotFoundError):
        await cache.read_bytes(path)

    path.write_bytes(b"available")
    assert await cache.read_bytes(path) == b"available"
    assert (await cache.stats()).loads == 1
