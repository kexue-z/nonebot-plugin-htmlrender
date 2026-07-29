from __future__ import annotations

from collections import Counter
from functools import partial
from typing import TYPE_CHECKING

import anyio
from anyio import wait_all_tasks_blocked
import pytest

from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    CachingResourceReader,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.adapters.resources import reader as reader_module
from nonebot_plugin_htmlrender.rendering.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)
from nonebot_plugin_htmlrender.resources.config import ResourceCacheSettings
from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    NotModified,
    PackageResourceRef,
    RemoteResourceRef,
    ResourceContent,
    ResourceRef,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.resources.ports import ResourceReader
    from tests.resources.conftest import (
        FailingCacheObserver,
        RecordingCacheObserver,
    )


def _content(value: bytes, revision: str) -> ResourceContent:
    return ResourceContent(
        value, "application/octet-stream", ResourceRevision(revision)
    )


class MemoryReader:
    def __init__(self, contents: dict[object, ResourceContent]) -> None:
        self.contents = contents
        self.reads: list[object] = []
        self.refreshes: list[bool] = []
        self.revisions: list[object] = []
        self.invalidated: list[object] = []
        self.clear_calls = 0

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        key = reference.cache_key
        self.reads.append(key)
        self.refreshes.append(refresh)
        return self.contents[key]

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent | NotModified:
        key = reference.cache_key
        self.revisions.append(key)
        if self.contents[key].revision == revision:
            return NotModified(revision)
        return await self.read(reference)

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        key = reference.cache_key
        self.revisions.append(key)
        return self.contents[key].revision

    async def invalidate(self, reference: ResourceRef) -> None:
        self.invalidated.append(reference.cache_key)

    async def clear(self) -> None:
        self.clear_calls += 1


class BlockingReader(MemoryReader):
    def __init__(self, contents: dict[object, ResourceContent]) -> None:
        super().__init__(contents)
        self.started = anyio.Event()
        self.release = anyio.Event()
        self.error: BaseException | None = None

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        key = reference.cache_key
        self.reads.append(key)
        self.refreshes.append(refresh)
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.contents[key]


class RefreshBlockingReader(MemoryReader):
    def __init__(self, contents: dict[object, ResourceContent]) -> None:
        super().__init__(contents)
        self.refresh_started = anyio.Event()
        self.release_refresh = anyio.Event()

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        key = reference.cache_key
        self.reads.append(key)
        self.refreshes.append(refresh)
        if refresh:
            self.refresh_started.set()
            await self.release_refresh.wait()
        return self.contents[key]


class TwoLoadBlockingReader(MemoryReader):
    def __init__(self, contents: dict[object, ResourceContent]) -> None:
        super().__init__(contents)
        self.first_started = anyio.Event()
        self.release_first = anyio.Event()
        self.second_started = anyio.Event()
        self.release_second = anyio.Event()

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        key = reference.cache_key
        self.reads.append(key)
        self.refreshes.append(refresh)
        captured = self.contents[key]
        if len(self.reads) == 1:
            self.first_started.set()
            await self.release_first.wait()
        elif len(self.reads) == 2:
            self.second_started.set()
            await self.release_second.wait()
        return captured


class ResetBlockingReader(MemoryReader):
    def __init__(self, contents: dict[object, ResourceContent]) -> None:
        super().__init__(contents)
        self.reset_started = anyio.Event()
        self.release_reset = anyio.Event()

    async def invalidate(self, reference: ResourceRef) -> None:
        await super().invalidate(reference)
        self.reset_started.set()
        await self.release_reset.wait()

    async def clear(self) -> None:
        self.clear_calls += 1
        self.reset_started.set()
        await self.release_reset.wait()


def _observed_events(observer: RecordingCacheObserver) -> Counter[str]:
    events: Counter[str] = Counter()
    for _, recorded, _, _ in observer.calls:
        events.update(recorded)
    return events


def _cache(
    inner: ResourceReader,
    *,
    max_entries: int = 8,
    max_bytes: int = 1024,
    revalidate_seconds: float = 60.0,
    observer: RecordingCacheObserver | FailingCacheObserver | None = None,
) -> CachingResourceReader:
    return CachingResourceReader(
        inner,
        settings=ResourceCacheSettings(
            max_entries=max_entries,
            max_bytes=max_bytes,
            revalidate_seconds=revalidate_seconds,
        ),
        observer=observer or NoopCacheObserver(),
    )


@pytest.mark.anyio
async def test_composite_reader_supports_all_reference_kinds(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    path = tmp_path / "asset.txt"
    path.write_text("filesystem", encoding="utf-8")
    reader = CompositeResourceReader(
        AnyioWorkerExecutor(),
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
    )

    file_content = await reader.read(FileResourceRef(path))
    package_content = await reader.read(
        PackageResourceRef(
            "nonebot_plugin_htmlrender",
            "templates/text/text.html",
        )
    )
    inline = InlineResourceRef(b"inline", "text/plain")
    inline_content = await reader.read(inline)

    remote_content = ResourceContent(
        b"remote",
        "text/plain",
        ResourceRevision("etag"),
    )
    remote_read = mocker.patch.object(
        reader_module,
        "read_remote",
        new=mocker.AsyncMock(return_value=remote_content),
    )
    remote = RemoteResourceRef("https://assets.example/card.css")

    assert file_content.data == b"filesystem"
    assert file_content.media_type == "text/plain"
    assert file_content.revision == await reader.revision(FileResourceRef(path))
    assert b"<head>" in package_content.data.lower()
    assert package_content.media_type == "text/html"
    assert package_content.revision == await reader.revision(
        PackageResourceRef(
            "nonebot_plugin_htmlrender",
            "templates/text/text.html",
        )
    )
    assert inline_content.data == b"inline"
    assert inline_content.media_type == "text/plain"
    assert inline_content.revision == await reader.revision(inline)
    assert await reader.read(remote) is remote_content
    assert await reader.revision(remote) is None
    remote_read.assert_called_once()
    assert remote_read.call_args.args == (remote,)
    assert remote_read.call_args.kwargs["max_resource_bytes"] == 64 * 1024 * 1024


@pytest.mark.anyio
async def test_composite_reader_enforces_per_resource_size_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"12345")
    reader = CompositeResourceReader(
        AnyioWorkerExecutor(),
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        max_resource_bytes=4,
    )

    with pytest.raises(ResourceSizeExceeded, match="4-byte read limit"):
        await reader.read(FileResourceRef(path))
    with pytest.raises(ResourceSizeExceeded, match="Inline resource"):
        await reader.read(InlineResourceRef(b"12345"))


@pytest.mark.anyio
async def test_composite_reader_translates_source_errors(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    reader = CompositeResourceReader(
        AnyioWorkerExecutor(),
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
    )
    missing = FileResourceRef(tmp_path / "missing.bin")

    with pytest.raises(ResourceNotFound):
        await reader.read(missing)
    with pytest.raises(ResourceNotFound):
        await reader.revision(missing)

    denied = FileResourceRef(tmp_path / "denied.bin")
    mocker.patch.object(
        reader_module, "_read_file", side_effect=PermissionError("denied")
    )
    with pytest.raises(ResourceAccessDenied, match="denied"):
        await reader.read(denied)

    remote = RemoteResourceRef("https://assets.example/missing.css")
    mocker.patch.object(
        reader_module,
        "read_remote",
        new=mocker.AsyncMock(
            side_effect=ResourceNotFound(f"Remote resource was not found: {remote.url}")
        ),
    )
    with pytest.raises(ResourceNotFound, match="was not found"):
        await reader.read(remote)

    mocker.patch.object(
        reader_module,
        "read_remote",
        new=mocker.AsyncMock(side_effect=OSError("connection reset")),
    )
    with pytest.raises(ResourceResolutionError, match="connection reset"):
        await reader.read(remote)


@pytest.mark.anyio
async def test_caching_reader_hits_and_revalidates_by_revision(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = MemoryReader({reference.cache_key: _content(b"v1", "one")})
    cached = _cache(inner, revalidate_seconds=0, observer=recording_observer)

    assert (await cached.read(reference)).data == b"v1"
    assert (await cached.read(reference)).data == b"v1"
    assert len(inner.reads) == 1
    assert len(inner.revisions) == 1
    assert recording_observer.calls[-1] == (
        "resource",
        {"hit": 1},
        1,
        2,
    )

    inner.contents[reference.cache_key] = _content(b"v2", "two")
    assert (await cached.read(reference)).data == b"v2"
    assert len(inner.reads) == 2


@pytest.mark.anyio
async def test_caching_reader_enforces_lru_and_byte_limits(
    recording_observer: RecordingCacheObserver,
) -> None:
    references = [InlineResourceRef(str(index).encode()) for index in range(4)]
    inner = MemoryReader(
        {
            reference.cache_key: _content(bytes([index, index]), str(index))
            for index, reference in enumerate(references)
        }
    )
    cached = _cache(
        inner,
        max_entries=2,
        max_bytes=4,
        observer=recording_observer,
    )

    await cached.read(references[0])
    await cached.read(references[1])
    await cached.read(references[0])
    await cached.read(references[2])
    await cached.read(references[1])

    assert inner.reads == [
        references[0].cache_key,
        references[1].cache_key,
        references[2].cache_key,
        references[1].cache_key,
    ]
    assert _observed_events(recording_observer)["eviction"] == 2


@pytest.mark.anyio
async def test_caching_reader_bypasses_oversized_content() -> None:
    reference = InlineResourceRef(b"large")
    inner = MemoryReader({reference.cache_key: _content(b"12345", "one")})
    cached = _cache(inner, max_bytes=4)

    assert (await cached.read(reference)).data == b"12345"
    assert (await cached.read(reference)).data == b"12345"
    assert len(inner.reads) == 2


@pytest.mark.anyio
async def test_caching_reader_invalidate_and_clear_are_instance_local() -> None:
    reference = InlineResourceRef(b"key")
    first_inner = MemoryReader({reference.cache_key: _content(b"first", "one")})
    second_inner = MemoryReader({reference.cache_key: _content(b"second", "two")})
    first = _cache(first_inner)
    second = _cache(second_inner)

    assert (await first.read(reference)).data == b"first"
    assert (await second.read(reference)).data == b"second"
    await first.invalidate(reference)
    await first.read(reference)
    await first.clear()
    await first.read(reference)

    assert len(first_inner.reads) == 3
    assert first_inner.invalidated == [reference.cache_key]
    assert first_inner.clear_calls == 1
    assert len(second_inner.reads) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["invalidate", "clear"])
async def test_cache_reset_detaches_stale_inflight_writeback(operation: str) -> None:
    reference = InlineResourceRef(b"key")
    inner = TwoLoadBlockingReader({reference.cache_key: _content(b"old", "one")})
    cached = _cache(inner)
    old_results: list[bytes] = []
    new_results: list[bytes] = []

    async def load_old() -> None:
        old_results.append((await cached.read(reference)).data)

    async def load_new() -> None:
        new_results.append((await cached.read(reference)).data)

    async with anyio.create_task_group() as group:
        group.start_soon(load_old)
        await inner.first_started.wait()
        inner.contents[reference.cache_key] = _content(b"new", "two")
        if operation == "invalidate":
            await cached.invalidate(reference)
        else:
            await cached.clear()
        group.start_soon(load_new)
        await inner.second_started.wait()
        inner.release_first.set()
        await wait_all_tasks_blocked()
        assert old_results == [b"old"]
        assert new_results == []
        inner.release_second.set()

    assert new_results == [b"new"]
    assert (await cached.read(reference)).data == b"new"
    assert len(inner.reads) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["invalidate", "clear"])
async def test_cache_reset_blocks_new_reads_until_inner_reset_finishes(
    operation: str,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = ResetBlockingReader({reference.cache_key: _content(b"old", "one")})
    cached = _cache(inner)

    assert (await cached.read(reference)).data == b"old"
    inner.contents[reference.cache_key] = _content(b"new", "two")
    results: list[bytes] = []

    async def reset() -> None:
        if operation == "invalidate":
            await cached.invalidate(reference)
        else:
            await cached.clear()

    async def read() -> None:
        results.append((await cached.read(reference)).data)

    async with anyio.create_task_group() as group:
        group.start_soon(reset)
        await inner.reset_started.wait()
        group.start_soon(read)
        await wait_all_tasks_blocked()
        assert results == []
        assert len(inner.reads) == 1
        inner.release_reset.set()

    assert results == [b"new"]
    assert len(inner.reads) == 2


@pytest.mark.anyio
async def test_singleflight_deduplicates_concurrent_reads() -> None:
    reference = InlineResourceRef(b"key")
    content = _content(b"value", "one")
    inner = BlockingReader({reference.cache_key: content})
    reader = _cache(inner, max_entries=0, max_bytes=0, revalidate_seconds=0)
    results: list[ResourceContent] = []

    async def read() -> None:
        results.append(await reader.read(reference))

    async with anyio.create_task_group() as group:
        group.start_soon(read)
        await inner.started.wait()
        for _ in range(8):
            group.start_soon(read)
        await wait_all_tasks_blocked()
        inner.release.set()

    assert len(inner.reads) == 1
    assert results == [content] * 9


@pytest.mark.anyio
async def test_singleflight_broadcasts_errors_without_caching_them() -> None:
    reference = InlineResourceRef(b"key")
    inner = BlockingReader({reference.cache_key: _content(b"value", "one")})
    inner.error = RuntimeError("read failed")
    reader = _cache(inner, max_entries=0, max_bytes=0, revalidate_seconds=0)
    errors: list[str] = []

    async def read() -> None:
        with pytest.raises(RuntimeError, match="read failed") as captured:
            await reader.read(reference)
        errors.append(str(captured.value))

    async with anyio.create_task_group() as group:
        group.start_soon(read)
        await inner.started.wait()
        for _ in range(4):
            group.start_soon(read)
        await wait_all_tasks_blocked()
        inner.release.set()

    assert errors == ["read failed"] * 5
    assert len(inner.reads) == 1

    inner.error = None
    assert (await reader.read(reference)).data == b"value"
    assert len(inner.reads) == 2


@pytest.mark.anyio
async def test_caching_reader_singleflights_metrics_and_writeback(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = BlockingReader({reference.cache_key: _content(b"value", "one")})
    reader = _cache(inner, observer=recording_observer)
    results: list[bytes] = []

    async def read() -> None:
        results.append((await reader.read(reference)).data)

    async with anyio.create_task_group() as group:
        group.start_soon(read)
        await inner.started.wait()
        for _ in range(6):
            group.start_soon(read)
        await wait_all_tasks_blocked()
        inner.release.set()

    assert results == [b"value"] * 7
    assert len(inner.reads) == 1
    assert _observed_events(recording_observer) == Counter(
        {"miss": 1, "load": 1, "wait": 6}
    )
    assert recording_observer.calls[-1][-2:] == (1, len(b"value"))


@pytest.mark.anyio
async def test_concurrent_refreshes_coalesce_and_supersede_cached_reads(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = RefreshBlockingReader({reference.cache_key: _content(b"old", "one")})
    reader = _cache(inner, observer=recording_observer)

    assert (await reader.read(reference)).data == b"old"
    inner.contents[reference.cache_key] = _content(b"new", "two")
    results: dict[str, bytes] = {}

    async def load(label: str, *, refresh: bool) -> None:
        results[label] = (await reader.read(reference, refresh=refresh)).data

    async with anyio.create_task_group() as group:
        group.start_soon(partial(load, "refresh-owner", refresh=True))
        await inner.refresh_started.wait()
        group.start_soon(partial(load, "refresh-waiter", refresh=True))
        group.start_soon(partial(load, "ordinary-waiter", refresh=False))
        await wait_all_tasks_blocked()
        assert results == {}
        assert len(inner.reads) == 2
        inner.release_refresh.set()

    assert results == {
        "refresh-owner": b"new",
        "refresh-waiter": b"new",
        "ordinary-waiter": b"new",
    }
    assert inner.refreshes == [False, True]
    assert _observed_events(recording_observer) == Counter(
        {"miss": 2, "load": 2, "wait": 2}
    )
    assert (await reader.read(reference)).data == b"new"


@pytest.mark.anyio
async def test_refresh_replaces_cold_load_without_crossing_waiter_groups(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = TwoLoadBlockingReader({reference.cache_key: _content(b"old", "one")})
    reader = _cache(inner, observer=recording_observer)
    old_results: list[bytes] = []
    refreshed_results: dict[str, bytes] = {}

    async def load_old() -> None:
        old_results.append((await reader.read(reference)).data)

    async def load_refreshed(label: str, *, refresh: bool) -> None:
        refreshed_results[label] = (await reader.read(reference, refresh=refresh)).data

    async with anyio.create_task_group() as group:
        group.start_soon(load_old)
        await inner.first_started.wait()
        group.start_soon(load_old)
        await wait_all_tasks_blocked()
        inner.contents[reference.cache_key] = _content(b"new", "two")
        group.start_soon(partial(load_refreshed, "refresh-owner", refresh=True))
        await inner.second_started.wait()
        group.start_soon(partial(load_refreshed, "refresh-waiter", refresh=True))
        group.start_soon(partial(load_refreshed, "ordinary-waiter", refresh=False))
        await wait_all_tasks_blocked()
        inner.release_first.set()
        await wait_all_tasks_blocked()
        assert old_results == [b"old", b"old"]
        assert refreshed_results == {}
        inner.release_second.set()

    assert refreshed_results == {
        "refresh-owner": b"new",
        "refresh-waiter": b"new",
        "ordinary-waiter": b"new",
    }
    assert inner.refreshes == [False, True]
    assert (await reader.read(reference)).data == b"new"
    assert len(inner.reads) == 2
    assert _observed_events(recording_observer) == Counter(
        {"miss": 2, "load": 2, "wait": 3, "hit": 1}
    )


@pytest.mark.anyio
async def test_singleflight_leader_cancellation_makes_waiter_retry(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = BlockingReader({reference.cache_key: _content(b"value", "one")})
    reader = _cache(inner, observer=recording_observer)
    owner_scope: anyio.CancelScope | None = None
    waiter_results: list[bytes] = []

    async def owner() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await reader.read(reference)

    async def waiter() -> None:
        waiter_results.append((await reader.read(reference)).data)

    async with anyio.create_task_group() as group:
        group.start_soon(owner)
        await inner.started.wait()
        group.start_soon(waiter)
        await wait_all_tasks_blocked()
        assert _observed_events(recording_observer)["wait"] == 1
        if owner_scope is None:
            raise AssertionError("owner cancellation scope was not initialized")
        owner_scope.cancel()
        await wait_all_tasks_blocked()
        assert len(inner.reads) == 2
        assert waiter_results == []
        inner.release.set()

    assert waiter_results == [b"value"]
    assert len(inner.reads) == 2
    assert (await reader.read(reference)).data == b"value"
    assert _observed_events(recording_observer) == Counter(
        {"miss": 2, "load": 1, "wait": 1, "hit": 1}
    )


@pytest.mark.anyio
async def test_singleflight_waiter_cancellation_keeps_shared_load_alive(
    recording_observer: RecordingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = BlockingReader({reference.cache_key: _content(b"value", "one")})
    reader = _cache(inner, observer=recording_observer)
    waiter_scope: anyio.CancelScope | None = None
    owner_results: list[bytes] = []

    async def owner() -> None:
        owner_results.append((await reader.read(reference)).data)

    async def waiter() -> None:
        nonlocal waiter_scope
        with anyio.CancelScope() as scope:
            waiter_scope = scope
            await reader.read(reference)

    async with anyio.create_task_group() as group:
        group.start_soon(owner)
        await inner.started.wait()
        group.start_soon(waiter)
        await wait_all_tasks_blocked()
        assert _observed_events(recording_observer)["wait"] == 1
        if waiter_scope is None:
            raise AssertionError("waiter cancellation scope was not initialized")
        waiter_scope.cancel()
        await wait_all_tasks_blocked()
        inner.release.set()

    assert owner_results == [b"value"]
    assert (await reader.read(reference)).data == b"value"
    assert len(inner.reads) == 1


@pytest.mark.anyio
async def test_reader_survives_failing_observer(
    failing_observer: FailingCacheObserver,
) -> None:
    reference = InlineResourceRef(b"key")
    inner = MemoryReader({reference.cache_key: _content(b"value", "one")})
    reader = _cache(inner, observer=failing_observer)

    assert (await reader.read(reference)).data == b"value"
    assert (await reader.read(reference)).data == b"value"


@pytest.mark.anyio
async def test_built_reader_serves_files_and_refreshes(tmp_path: Path) -> None:
    path = tmp_path / "resource.txt"
    path.write_text("one", encoding="utf-8")
    reader = build_resource_reader(
        ResourceCacheSettings(revalidate_seconds=60),
        NoopCacheObserver(),
        AnyioWorkerExecutor(),
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
    )
    reference = FileResourceRef(path)

    assert (await reader.read(reference)).data == b"one"
    path.write_text("two", encoding="utf-8")
    assert (await reader.read(reference)).data == b"one"
    await reader.invalidate(reference)
    assert (await reader.read(reference)).data == b"two"


def test_configured_local_access_policy_keeps_instances_isolated(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_path = first_root / "asset.bin"
    second_path = second_root / "asset.bin"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first = ConfiguredLocalAccessPolicy(allowed_roots=(first_root,), allow_any=False)
    second = ConfiguredLocalAccessPolicy(allowed_roots=(second_root,), allow_any=False)

    assert first.authorize(first_path) == first_path.resolve()
    assert second.authorize(second_path) == second_path.resolve()
    with pytest.raises(ResourceAccessDenied, match="outside allowed roots"):
        first.authorize(second_path)
