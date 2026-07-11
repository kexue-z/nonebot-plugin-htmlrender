from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from typing import TYPE_CHECKING

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.resources import filehost as filehost_runtime
from nonebot_plugin_htmlrender.resources.config import ResourceConfig
from nonebot_plugin_htmlrender.resources.filehost import cache as _cache_mod
from nonebot_plugin_htmlrender.resources.filehost import guard as _guard_mod
from nonebot_plugin_htmlrender.resources.filehost import warmup as _warmup_mod

if TYPE_CHECKING:
    from pathlib import Path
    from typing import ClassVar

    from pytest_mock import MockerFixture


def _cfg(
    *,
    mode: str = "auto",
    remote_policy: str = "filehost",
    local_policy: str = "file",
    header_name: str = "X-HTMLRender-Filehost-Request",
    header_value: str | None = None,
    header_salt: str = "nonebot-plugin-htmlrender:filehost:guard:v1",
) -> ResourceConfig:
    return ResourceConfig(
        resource_resolve_mode=ResourceResolveMode(mode),
        remote_local_resource_policy=RemoteLocalResourcePolicy(remote_policy),
        local_local_resource_policy=LocalLocalResourcePolicy(local_policy),
        filehost_allow_any_path=True,
        filehost_request_header_name=header_name,
        filehost_request_header_value=header_value,
        filehost_request_header_salt=header_salt,
        filehost_prewarm_enabled=True,
        filehost_prewarm_max_files=4,
        filehost_prewarm_extensions=(".css",),
        filehost_cache_ttl_seconds=300.0,
    )


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    filehost_runtime._FILEHOST_PREWARM_STATE["url"] = None
    filehost_runtime._FILEHOST_PREWARM_STATE["last_error"] = None
    filehost_runtime._FILEHOST_GUARD_STATE["installed"] = False
    filehost_runtime._FILEHOST_GUARD_STATE["token"] = None
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    filehost_runtime._FILEHOST_PATH_INDEX.clear()
    filehost_runtime._FILEHOST_LEASES.clear()
    filehost_runtime._FILEHOST_REGISTERED_ROOTS.clear()
    _cache_mod._FILEHOST_COUNTERS.uploaded_bytes = 0
    _cache_mod._FILEHOST_COUNTERS.dedup_hits = 0


def test_filehost_normalize_and_prewarm_path_rules(tmp_path: Path) -> None:
    assert filehost_runtime._normalize_filehost_input(bytearray(b"x")) == b"x"
    assert filehost_runtime._normalize_filehost_input(BytesIO(b"y")) == b"y"

    folder = tmp_path / "dir"
    folder.mkdir()
    css_file = tmp_path / "style.css"
    css_file.write_text("body{}", encoding="utf-8")
    html_file = tmp_path / "card.html"
    html_file.write_text("<html/>", encoding="utf-8")

    assert filehost_runtime._should_prewarm_path(folder, {".css"}) is False
    assert filehost_runtime._should_prewarm_path(html_file, {".css", ".html"}) is False
    assert filehost_runtime._should_prewarm_path(css_file, set()) is True
    assert filehost_runtime._should_prewarm_path(css_file, {".css"}) is True


def test_attach_key_to_lease_locked_branches() -> None:
    lease = "lease:x"
    key = "cache:key"
    filehost_runtime._FILEHOST_LEASES[lease] = {key}
    filehost_runtime._FILEHOST_RESOURCE_CACHE[key] = {
        "url": "http://render/filehost/x",
        "digest": "x",
        "size": 1,
        "hits": 0,
        "last_access_ns": 0,
        "lease_ref_count": 0,
        "mapping_expires_at_ns": 1,
        "path_aliases": set(),
        "suffix": ".bin",
    }

    # duplicate key should be ignored
    filehost_runtime._attach_key_to_lease_locked(lease, key)
    assert filehost_runtime._FILEHOST_RESOURCE_CACHE[key]["lease_ref_count"] == 0

    # A released or unknown lease must not be resurrected by a late upload.
    filehost_runtime._FILEHOST_LEASES[lease] = set()
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._attach_key_to_lease_locked(lease, key)
    assert key not in filehost_runtime._FILEHOST_LEASES[lease]


def test_headers_disabled_and_guard_token_defaults(mocker: MockerFixture) -> None:
    mocker.patch.object(
        filehost_runtime, "get_resource_config", return_value=_cfg(mode="off")
    )
    assert filehost_runtime.get_filehost_request_headers() == {}

    mocker.patch.object(
        _guard_mod,
        "get_resource_config",
        return_value=_cfg(header_name="   "),
    )
    name, value = filehost_runtime._get_request_guard_header_config()
    assert name == "X-HTMLRender-Filehost-Request"
    assert isinstance(value, str)
    assert filehost_runtime._is_valid_guard_token(None) is False


def test_resolve_device_identifier_machineid_error_and_mac_fallback(
    mocker: MockerFixture,
) -> None:
    fake_module = SimpleNamespace(id=mocker.Mock(side_effect=RuntimeError("bad id")))
    mocker.patch.object(_guard_mod, "import_module", return_value=fake_module)
    mocker.patch.object(_guard_mod.uuid, "getnode", return_value=0xAABBCC)

    value = filehost_runtime._resolve_device_identifier()
    assert value == "mac:000000aabbcc"


def test_ensure_filehost_request_guard_installed_paths(
    mocker: MockerFixture,
) -> None:
    # already installed
    filehost_runtime._FILEHOST_GUARD_STATE["installed"] = True
    assert (
        filehost_runtime.ensure_filehost_request_guard_installed(reason="unit") is True
    )
    filehost_runtime._FILEHOST_GUARD_STATE["installed"] = False

    # non-ASGI
    mocker.patch.object(_guard_mod, "get_driver", return_value=object())
    assert (
        filehost_runtime.ensure_filehost_request_guard_installed(reason="unit") is False
    )

    # non-FastAPI app
    mocker.patch.object(_guard_mod, "ASGIMixin", object)
    mocker.patch.object(
        _guard_mod,
        "get_driver",
        return_value=SimpleNamespace(server_app=object()),
    )
    assert (
        filehost_runtime.ensure_filehost_request_guard_installed(reason="unit") is False
    )

    # success path with middleware behavior
    app = FastAPI()

    @app.get("/filehost/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "true"}

    mocker.patch.object(
        _guard_mod,
        "get_resource_config",
        return_value=_cfg(header_value="token-fixed"),
    )
    mocker.patch.object(
        _guard_mod,
        "get_driver",
        return_value=SimpleNamespace(server_app=app),
    )
    assert (
        filehost_runtime.ensure_filehost_request_guard_installed(reason="unit") is True
    )

    client = TestClient(app)
    blocked = client.get("/filehost/ping")
    assert blocked.status_code == 403

    passed = client.get(
        "/filehost/ping",
        headers={"X-HTMLRender-Filehost-Request": "token-fixed"},
    )
    assert passed.status_code == 200


def test_ensure_filehost_request_guard_installed_returns_false_when_app_started(
    mocker: MockerFixture,
) -> None:
    app = FastAPI()
    mocker.patch.object(
        app,
        "add_middleware",
        side_effect=RuntimeError(
            "Cannot add middleware after an application has started"
        ),
    )
    mocker.patch.object(
        _guard_mod,
        "get_resource_config",
        return_value=_cfg(header_value="token-fixed"),
    )
    mocker.patch.object(
        _guard_mod,
        "get_driver",
        return_value=SimpleNamespace(server_app=app),
    )

    assert (
        filehost_runtime.ensure_filehost_request_guard_installed(reason="unit") is False
    )


def test_ensure_filehost_plugin_loaded_exception_paths(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(_warmup_mod, "find_spec", return_value=None)
    assert filehost_runtime.ensure_filehost_plugin_loaded(reason="unit") is False

    mocker.patch.object(_warmup_mod, "find_spec", return_value=object())
    mocker.patch.object(
        _warmup_mod, "require", side_effect=RuntimeError("missing plugin")
    )
    assert filehost_runtime.ensure_filehost_plugin_loaded(reason="unit") is False


def test_ensure_filehost_plugin_loaded_strict_mode_raises(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(_warmup_mod, "find_spec", return_value=object())
    mocker.patch.object(
        _warmup_mod, "require", side_effect=RuntimeError("missing plugin")
    )

    with pytest.raises(RuntimeError, match=r"Filehost plugin bootstrap failed"):
        filehost_runtime.ensure_filehost_plugin_loaded(reason="unit", strict=True)


@pytest.mark.anyio
async def test_filehost_upload_success_and_import_failure(
    mocker: MockerFixture,
) -> None:
    class _Uploader:
        suffixes: ClassVar[list[str]] = []

        def __init__(self, _value: object, *, suffix: str = "") -> None:
            self.suffixes.append(suffix)

        async def to_url(self) -> str:
            return "http://render/filehost/u"

    mocker.patch.object(
        _cache_mod,
        "import_module",
        return_value=SimpleNamespace(FileHost=_Uploader),
    )
    assert await filehost_runtime._filehost_upload(b"x") == "http://render/filehost/u"
    assert (
        await filehost_runtime._filehost_upload(b"x", suffix=".css")
        == "http://render/filehost/u"
    )
    assert _Uploader.suffixes == ["", ".css"]

    mocker.patch.object(_cache_mod, "import_module", side_effect=RuntimeError("oops"))
    with pytest.raises(RuntimeError, match="nonebot-plugin-filehost is required"):
        await filehost_runtime._filehost_upload(b"x")


@pytest.mark.anyio
async def test_filehost_url_from_path_cache_and_inflight_branches(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    asset = tmp_path / "a.css"
    asset.write_text("x", encoding="utf-8")
    upload = mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(return_value="http://uploaded"),
    )

    lease = filehost_runtime.create_filehost_lease()
    assert (
        await filehost_runtime._filehost_url_from_path(asset, lease_id=lease)
        == "http://uploaded"
    )
    assert (
        await filehost_runtime._filehost_url_from_path(asset, lease_id=lease)
        == "http://uploaded"
    )
    upload.assert_awaited_once_with(b"x", suffix=".css")

    key = next(iter(filehost_runtime._FILEHOST_RESOURCE_CACHE))
    assert key.startswith("sha256:")
    assert key in filehost_runtime._FILEHOST_LEASES[lease]
    assert filehost_runtime._FILEHOST_RESOURCE_CACHE[key]["lease_ref_count"] == 1
    assert filehost_runtime._FILEHOST_PATH_INDEX[asset.resolve()].blob_key == key

    # owner upload failure path
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    filehost_runtime._FILEHOST_PATH_INDEX.clear()
    mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(side_effect=RuntimeError("upload fail")),
    )
    with pytest.raises(RuntimeError, match="upload fail"):
        await filehost_runtime._filehost_url_from_path(asset)


@pytest.mark.anyio
async def test_filehost_deduplicates_equal_path_and_byte_snapshots(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"shared")
    second.write_bytes(b"shared")
    upload = mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/shared"),
    )
    leases = [filehost_runtime.create_filehost_lease() for _ in range(5)]

    urls = [
        await filehost_runtime.filehost_url(first, lease_id=leases[0]),
        await filehost_runtime.filehost_url(second, lease_id=leases[1]),
        await filehost_runtime.filehost_url(b"shared", lease_id=leases[2]),
        await filehost_runtime.filehost_url(bytearray(b"shared"), lease_id=leases[3]),
        await filehost_runtime.filehost_url(BytesIO(b"shared"), lease_id=leases[4]),
    ]

    assert urls == ["http://render/filehost/shared"] * 5
    upload.assert_awaited_once_with(b"shared", suffix=".bin")
    assert len(filehost_runtime._FILEHOST_RESOURCE_CACHE) == 1
    key, entry = next(iter(filehost_runtime._FILEHOST_RESOURCE_CACHE.items()))
    assert key == f"sha256:{entry['digest']}"
    assert entry["lease_ref_count"] == len(leases)
    assert all(filehost_runtime._FILEHOST_LEASES[lease] == {key} for lease in leases)


@pytest.mark.anyio
async def test_filehost_cache_reports_low_cardinality_metrics(
    mocker: MockerFixture,
) -> None:
    export = mocker.patch.object(_cache_mod, "record_filehost_cache_metrics")
    mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/metric"),
    )

    assert await filehost_runtime.filehost_url(b"metric") == (
        "http://render/filehost/metric"
    )
    assert await filehost_runtime.filehost_url(b"metric") == (
        "http://render/filehost/metric"
    )
    metrics = await filehost_runtime.get_filehost_cache_metrics()

    assert metrics.uploaded_bytes == len(b"metric")
    assert metrics.dedup_hits == 1
    assert metrics.active_mappings == 1
    assert metrics.active_leases == 0
    assert metrics.physical_cleanup_capable == 0
    assert [call.args[:2] for call in export.call_args_list] == [
        ("upload", len(b"metric")),
        ("dedup", 1),
    ]


@pytest.mark.anyio
async def test_filehost_path_revisions_keep_distinct_lease_bindings(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    asset = tmp_path / "mutable.bin"
    asset.write_bytes(b"first")
    first_lease = filehost_runtime.create_filehost_lease()
    second_lease = filehost_runtime.create_filehost_lease()
    upload_count = 0

    async def upload(snapshot: object, *, suffix: str = "") -> str:
        nonlocal upload_count
        assert suffix == ".bin"
        upload_count += 1
        if upload_count == 1:
            assert snapshot == b"first"
            # Mutate the source after the consistent snapshot was taken. The first
            # URL must still represent the exact bytes supplied to the uploader.
            asset.write_bytes(b"second-revision")
            return "http://render/filehost/first"
        assert snapshot == b"second-revision"
        return "http://render/filehost/second"

    mocker.patch.object(_cache_mod, "_filehost_upload", side_effect=upload)

    first_url = await filehost_runtime.filehost_url(asset, lease_id=first_lease)
    second_url = await filehost_runtime.filehost_url(asset, lease_id=second_lease)

    assert first_url == "http://render/filehost/first"
    assert second_url == "http://render/filehost/second"
    assert upload_count == 2
    first_keys = filehost_runtime._FILEHOST_LEASES[first_lease]
    second_keys = filehost_runtime._FILEHOST_LEASES[second_lease]
    assert len(first_keys) == len(second_keys) == 1
    assert first_keys.isdisjoint(second_keys)
    assert len(filehost_runtime._FILEHOST_RESOURCE_CACHE) == 2

    await filehost_runtime.release_filehost_lease(first_lease)
    first_entry = filehost_runtime._FILEHOST_RESOURCE_CACHE[next(iter(first_keys))]
    second_entry = filehost_runtime._FILEHOST_RESOURCE_CACHE[next(iter(second_keys))]
    assert first_entry["mapping_expires_at_ns"] is not None
    assert second_entry["mapping_expires_at_ns"] is None


@pytest.mark.anyio
async def test_filehost_concurrent_bytes_singleflight(
    mocker: MockerFixture,
) -> None:
    upload_started = anyio.Event()
    release_upload = anyio.Event()
    upload_count = 0
    results: list[str] = []

    async def upload(value: object) -> str:
        nonlocal upload_count
        assert value == b"same"
        upload_count += 1
        upload_started.set()
        await release_upload.wait()
        return "http://render/filehost/same"

    mocker.patch.object(_cache_mod, "_filehost_upload", side_effect=upload)

    async def resolve(value: bytes | bytearray | BytesIO) -> None:
        results.append(await filehost_runtime.filehost_url(value))

    async with anyio.create_task_group() as task_group:
        for index in range(18):
            value: bytes | bytearray | BytesIO
            if index % 3 == 0:
                value = b"same"
            elif index % 3 == 1:
                value = bytearray(b"same")
            else:
                value = BytesIO(b"same")
            task_group.start_soon(resolve, value)
        await upload_started.wait()
        release_upload.set()

    assert results == ["http://render/filehost/same"] * 18
    assert upload_count == 1


@pytest.mark.anyio
async def test_filehost_owner_cancellation_releases_waiters(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    asset = tmp_path / "cancelled.css"
    asset.write_text("x", encoding="utf-8")
    started = anyio.Event()
    never_finish = anyio.Event()
    waiter_waiting = anyio.Event()
    owner_scope: anyio.CancelScope | None = None
    waiter_error: BaseException | None = None

    real_event_factory = anyio.Event

    class _InstrumentedEvent:
        def __init__(self) -> None:
            self._event = real_event_factory()

        async def wait(self) -> None:
            waiter_waiting.set()
            await self._event.wait()

        def set(self) -> None:
            self._event.set()

    mocker.patch.object(_cache_mod.anyio, "Event", _InstrumentedEvent)

    async def blocked_upload(value: object, *, suffix: str = "") -> str:
        del value
        assert suffix == ".css"
        started.set()
        await never_finish.wait()
        return "http://unreachable"

    mocker.patch.object(_cache_mod, "_filehost_upload", side_effect=blocked_upload)

    async def owner() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await filehost_runtime._filehost_url_from_path(asset)

    async def waiter() -> None:
        nonlocal waiter_error
        try:
            await filehost_runtime._filehost_url_from_path(asset)
        except BaseException as error:
            waiter_error = error

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(owner)
        await started.wait()
        task_group.start_soon(waiter)
        await waiter_waiting.wait()
        assert owner_scope is not None
        owner_scope.cancel()

    assert isinstance(waiter_error, RuntimeError)
    assert "cancelled" in str(waiter_error)
    assert not filehost_runtime._FILEHOST_RESOURCE_INFLIGHT


@pytest.mark.anyio
async def test_filehost_rejects_conflicting_suffixes_for_one_digest(
    mocker: MockerFixture,
) -> None:
    upload = mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/value.css"),
    )

    assert await filehost_runtime.filehost_url(b"same", suffix="css") == (
        "http://render/filehost/value.css"
    )
    with pytest.raises(RuntimeError, match="incompatible suffixes"):
        await filehost_runtime.filehost_url(b"same", suffix=".woff2")

    upload.assert_awaited_once_with(b"same", suffix=".css")


@pytest.mark.anyio
async def test_filehost_cancellation_after_upload_publishes_to_waiters(
    mocker: MockerFixture,
) -> None:
    upload_started = anyio.Event()
    release_upload = anyio.Event()
    waiter_waiting = anyio.Event()
    owner_scope: anyio.CancelScope | None = None
    waiter_url: str | None = None
    real_event_factory = anyio.Event

    class _InstrumentedEvent:
        def __init__(self) -> None:
            self._event = real_event_factory()

        async def wait(self) -> None:
            waiter_waiting.set()
            await self._event.wait()

        def set(self) -> None:
            self._event.set()

    mocker.patch.object(_cache_mod.anyio, "Event", _InstrumentedEvent)

    async def upload(value: object) -> str:
        assert value == b"publish"
        upload_started.set()
        await release_upload.wait()
        assert owner_scope is not None
        owner_scope.cancel()
        return "http://render/filehost/published"

    mocker.patch.object(_cache_mod, "_filehost_upload", side_effect=upload)

    async def owner() -> None:
        nonlocal owner_scope
        with anyio.CancelScope() as scope:
            owner_scope = scope
            await filehost_runtime.filehost_url(b"publish")

    async def waiter() -> None:
        nonlocal waiter_url
        waiter_url = await filehost_runtime.filehost_url(b"publish")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(owner)
        await upload_started.wait()
        task_group.start_soon(waiter)
        await waiter_waiting.wait()
        release_upload.set()

    assert waiter_url == "http://render/filehost/published"
    assert len(filehost_runtime._FILEHOST_RESOURCE_CACHE) == 1
    assert not filehost_runtime._FILEHOST_RESOURCE_INFLIGHT


@pytest.mark.anyio
async def test_prewarm_directories_and_runtime_ready_exception_paths(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    # prewarm disabled
    mocker.patch.object(_warmup_mod, "_prewarm_enabled", return_value=False)
    assert await filehost_runtime._prewarm_resource_directories(reason="unit") == (0, 0)

    # prewarm with exception and max-file break
    root1 = tmp_path / "r1"
    root2 = tmp_path / "r2"
    root1.mkdir()
    root2.mkdir()
    (root1 / "a.css").write_text("x", encoding="utf-8")
    (root2 / "b.css").write_text("y", encoding="utf-8")
    mocker.patch.object(_warmup_mod, "_prewarm_enabled", return_value=True)
    mocker.patch.object(
        _warmup_mod,
        "get_resource_config",
        return_value=ResourceConfig(
            resource_resolve_mode=ResourceResolveMode.AUTO,
            remote_local_resource_policy=RemoteLocalResourcePolicy.FILEHOST,
            local_local_resource_policy=LocalLocalResourcePolicy.FILE,
            filehost_allow_any_path=True,
            filehost_prewarm_max_files=1,
            filehost_prewarm_extensions=(".css",),
        ),
    )
    mocker.patch.object(
        _warmup_mod, "_collect_prewarm_roots", return_value=[root1, root2]
    )
    mocker.patch.object(
        _warmup_mod,
        "filehost_url",
        new=mocker.AsyncMock(side_effect=RuntimeError("skip one")),
    )
    logger_warning = mocker.patch.object(_warmup_mod.logger, "warning")
    scanned, warmed = await filehost_runtime._prewarm_resource_directories(
        reason="unit"
    )
    assert scanned == 1
    assert warmed == 0
    logger_warning.assert_called_once()

    # runtime ready config exception
    mocker.patch.object(
        filehost_runtime,
        "_is_filehost_resolution_enabled",
        side_effect=RuntimeError("bad"),
    )
    assert await filehost_runtime.ensure_filehost_runtime_ready(reason="unit") is False
