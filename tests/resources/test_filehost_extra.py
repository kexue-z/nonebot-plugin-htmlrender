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
    filehost_runtime._FILEHOST_LEASES.clear()
    filehost_runtime._FILEHOST_REGISTERED_ROOTS.clear()


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
    filehost_runtime._FILEHOST_RESOURCE_CACHE[key] = {  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-assignment,missing-typed-dict-key]
        "lease_ref_count": 0,
        "expires_at_ns": 1,
    }

    # duplicate key should be ignored
    filehost_runtime._attach_key_to_lease_locked(lease, key)
    assert filehost_runtime._FILEHOST_RESOURCE_CACHE[key]["lease_ref_count"] == 0

    # missing cache entry should not crash
    filehost_runtime._FILEHOST_LEASES[lease] = set()
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._attach_key_to_lease_locked(lease, key)
    assert key in filehost_runtime._FILEHOST_LEASES[lease]


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
        def __init__(self, _value: object) -> None:
            pass

        async def to_url(self) -> str:
            return "http://render/filehost/u"

    mocker.patch.object(
        _cache_mod,
        "import_module",
        return_value=SimpleNamespace(FileHost=_Uploader),
    )
    assert await filehost_runtime._filehost_upload(b"x") == "http://render/filehost/u"

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
    resolved = asset.resolve()
    key = str(resolved)
    mtime_ns = resolved.stat().st_mtime_ns
    size = resolved.stat().st_size
    mocker.patch.object(
        _cache_mod,
        "_normalize_and_snapshot_path",
        return_value=(resolved, key, mtime_ns, size),
    )
    upload = mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(return_value="http://uploaded"),
    )

    # cached hit + lease attach
    filehost_runtime._FILEHOST_RESOURCE_CACHE[key] = {
        "url": "http://cached",
        "mtime_ns": mtime_ns,
        "size": size,
        "hits": 0,
        "last_access_ns": 0,
        "lease_ref_count": 0,
        "expires_at_ns": 2**63,
    }
    lease = filehost_runtime.create_filehost_lease()
    assert (
        await filehost_runtime._filehost_url_from_path(asset, lease_id=lease)
        == "http://cached"
    )
    upload.assert_not_awaited()

    # inflight done entry
    done_entry = filehost_runtime._InflightResourceUpload(
        event=anyio.Event(), url="http://done"
    )
    done_entry.event.set()
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT[key] = done_entry
    assert await filehost_runtime._filehost_url_from_path(asset) == "http://done"

    # owner upload failure path
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    mocker.patch.object(
        _cache_mod,
        "_filehost_upload",
        new=mocker.AsyncMock(side_effect=RuntimeError("upload fail")),
    )
    with pytest.raises(RuntimeError, match="upload fail"):
        await filehost_runtime._filehost_url_from_path(asset)


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
