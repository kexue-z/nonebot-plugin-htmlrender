import asyncio
import hashlib
from importlib import import_module
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.resources.config import ResourceConfig


def _make_cfg(
    *,
    mode: str,
    remote_policy: str = "passthrough",
    local_policy: str = "file",
    is_remote_mode: bool = False,
    filehost_allow_any_path: bool = False,
    filehost_allowed_paths: list[Path] | None = None,
    filehost_request_header_name: str = "X-HTMLRender-Filehost-Request",
    filehost_request_header_value: str | None = None,
    filehost_request_header_salt: str = "nonebot-plugin-htmlrender:filehost:guard:v1",
    filehost_prewarm_enabled: bool = True,
    filehost_prewarm_max_files: int = 256,
    filehost_cache_ttl_seconds: float = 300.0,
    filehost_prewarm_extensions: list[str] | None = None,
    filehost_prewarm_paths: list[Path] | None = None,
) -> ResourceConfig:
    return ResourceConfig(
        is_remote_mode=is_remote_mode,
        resource_resolve_mode=ResourceResolveMode(mode),
        remote_local_resource_policy=RemoteLocalResourcePolicy(remote_policy),
        local_local_resource_policy=LocalLocalResourcePolicy(local_policy),
        filehost_allow_any_path=filehost_allow_any_path,
        filehost_allowed_paths=tuple(filehost_allowed_paths or []),
        filehost_request_header_name=filehost_request_header_name,
        filehost_request_header_value=filehost_request_header_value,
        filehost_request_header_salt=filehost_request_header_salt,
        filehost_prewarm_enabled=filehost_prewarm_enabled,
        filehost_prewarm_max_files=filehost_prewarm_max_files,
        filehost_cache_ttl_seconds=filehost_cache_ttl_seconds,
        filehost_prewarm_extensions=tuple(
            filehost_prewarm_extensions
            or [
                ".css",
                ".js",
                ".png",
                ".jpg",
                ".jpeg",
                ".svg",
                ".woff",
                ".woff2",
            ]
        ),
        filehost_prewarm_paths=tuple(filehost_prewarm_paths or []),
    )


@pytest.fixture(autouse=True)
def reset_filehost_prewarm_state() -> None:
    import nonebot_plugin_htmlrender.resources.filehost as filehost_runtime  # noqa: PLC0415

    filehost_runtime._FILEHOST_PREWARM_STATE["url"] = None
    filehost_runtime._FILEHOST_PREWARM_STATE["last_error"] = None
    filehost_runtime._FILEHOST_GUARD_STATE["installed"] = False
    filehost_runtime._FILEHOST_GUARD_STATE["token"] = None


@pytest.mark.anyio
async def test_resolve_template_vars_local_path_to_file_url(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_template_vars,
    )

    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    asset = asset_dir / "avatar.png"
    asset.write_bytes(b"test")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(mode="auto", local_policy="file"),
    )

    resolved = await resolve_template_vars(
        {"avatar": "assets/avatar.png"},
        template_base=tmp_path,
    )

    assert resolved["avatar"] == asset.resolve().as_uri()


@pytest.mark.anyio
async def test_resolve_template_vars_remote_uses_filehost(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_template_vars,
    )

    asset = tmp_path / "avatar.png"
    asset.write_bytes(b"test")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(
            mode="auto",
            remote_policy="filehost",
            is_remote_mode=True,
        ),
    )
    filehost_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(return_value="https://example.com/avatar.png"),
    )

    resolved = await resolve_template_vars({"avatar": asset}, template_base=tmp_path)

    assert resolved["avatar"] == "https://example.com/avatar.png"
    filehost_mock.assert_awaited_once_with(asset.resolve(), lease_id=None)


@pytest.mark.anyio
async def test_resolve_template_vars_strict_raises_on_filehost_failure(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        ResourceResolveError,
        resolve_template_vars,
    )

    asset = tmp_path / "avatar.png"
    asset.write_bytes(b"test")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(
            mode="strict",
            remote_policy="filehost",
            is_remote_mode=True,
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(side_effect=RuntimeError("filehost unavailable")),
    )

    with pytest.raises(ResourceResolveError, match="filehost unavailable"):
        await resolve_template_vars(
            {"avatar": asset},
            template_base=tmp_path,
            strict=True,
        )


@pytest.mark.anyio
async def test_resolve_template_vars_off_mode_keeps_original(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_template_vars,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(mode="off"),
    )

    source = {"avatar": "./assets/avatar.png"}
    resolved = await resolve_template_vars(source)

    assert resolved == source


@pytest.mark.anyio
async def test_to_resource_url_force_filehost(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import to_resource_url  # noqa: PLC0415

    asset = tmp_path / "logo.svg"
    asset.write_text("<svg></svg>", encoding="utf-8")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(mode="off", filehost_allow_any_path=True),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(return_value="https://example.com/logo.svg"),
    )

    result = await to_resource_url(asset, resolver="filehost")

    assert result == "https://example.com/logo.svg"


@pytest.mark.anyio
async def test_resolve_template_vars_filehost_rejects_path_outside_template_base(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        ResourceResolveError,
        resolve_template_vars,
    )

    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    outside = tmp_path / "secrets" / "private.txt"
    outside.parent.mkdir()
    outside.write_text("secret", encoding="utf-8")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(
            mode="auto",
            remote_policy="filehost",
            is_remote_mode=True,
        ),
    )

    with pytest.raises(ResourceResolveError, match="outside allowed filehost roots"):
        await resolve_template_vars(
            {"secret": outside},
            template_base=template_dir,
            strict=True,
        )


@pytest.mark.anyio
async def test_resolve_template_vars_filehost_allows_explicit_allowed_roots(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_template_vars,
    )

    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    shared_file = shared_dir / "avatar.png"
    shared_file.write_bytes(b"ok")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(
            mode="auto",
            remote_policy="filehost",
            is_remote_mode=True,
            filehost_allowed_paths=[shared_dir],
        ),
    )
    filehost_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(return_value="https://example.com/shared/avatar.png"),
    )

    resolved = await resolve_template_vars(
        {"avatar": shared_file},
        template_base=template_dir,
        strict=True,
    )

    assert resolved["avatar"] == "https://example.com/shared/avatar.png"
    filehost_mock.assert_awaited_once_with(shared_file.resolve(), lease_id=None)


@pytest.mark.anyio
async def test_resolve_html_resources_rewrites_attrs_and_css_urls_with_filehost(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_html_resources,
    )

    assets = tmp_path / "assets"
    images = assets / "images"
    fonts = assets / "fonts"
    assets.mkdir()
    images.mkdir()
    fonts.mkdir()
    (assets / "style.css").write_text("body {}", encoding="utf-8")
    (images / "logo.png").write_bytes(b"img")
    (fonts / "site.woff2").write_bytes(b"font")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(
            mode="auto",
            remote_policy="filehost",
            is_remote_mode=True,
        ),
    )

    async def _fake_filehost_url(value, *, lease_id=None):
        del lease_id
        return f"https://render.local/filehost/{Path(value).name}"

    filehost_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(side_effect=_fake_filehost_url),
    )

    html = (
        '<link rel="stylesheet" href="assets/style.css?rev=1">'
        '<img src="assets/images/logo.png">'
        "<style>@font-face{src:url('assets/fonts/site.woff2');}</style>"
    )
    rewritten = await resolve_html_resources(
        html,
        template_base=tmp_path,
        resolver="auto",
        strict=True,
    )

    assert 'href="https://render.local/filehost/style.css?rev=1"' in rewritten
    assert 'src="https://render.local/filehost/logo.png"' in rewritten
    assert "url('https://render.local/filehost/site.woff2')" in rewritten
    assert filehost_mock.await_count == 3


@pytest.mark.anyio
async def test_resolve_html_resources_keeps_external_and_anchor_links(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.resources import (  # noqa: PLC0415
        resolve_html_resources,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    filehost_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.resolve.filehost_url",
        new=mocker.AsyncMock(),
    )

    html = (
        '<a href="#section">go</a>'
        '<a href="https://example.com/x.css">external</a>'
        "<style>.x{background-image:url('https://example.com/bg.png')}</style>"
    )
    rewritten = await resolve_html_resources(
        html,
        template_base=tmp_path,
        resolver="auto",
        strict=True,
    )

    assert rewritten == html
    filehost_mock.assert_not_called()


@pytest.mark.anyio
async def test_filehost_prewarm_skips_when_not_enabled(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        ensure_filehost_runtime_ready,
        get_filehost_prewarm_status,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="off"),
    )
    require_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.require"
    )
    filehost_url_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.filehost_url",
        new=mocker.AsyncMock(),
    )

    assert await ensure_filehost_runtime_ready(reason="unit") is False
    require_mock.assert_not_called()
    filehost_url_mock.assert_not_awaited()
    status = get_filehost_prewarm_status()
    assert status["ready"] == "false"
    assert status["url"] is None
    assert status["last_error"] is None
    assert status["cached_resources"] is not None
    assert status["cached_url_mappings"] == status["cached_resources"]
    assert status["ttl_scope"] == "url_mapping"
    assert status["physical_cleanup_supported"] == "false"


@pytest.mark.anyio
async def test_filehost_prewarm_is_idempotent_after_success(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        ensure_filehost_runtime_ready,
        get_filehost_prewarm_status,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    guard_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.ensure_filehost_request_guard_installed",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.find_spec",
        return_value=object(),
    )
    require_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.require"
    )
    filehost_url_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.filehost_url",
        new=mocker.AsyncMock(return_value="http://render:9012/filehost/prewarm"),
    )

    assert await ensure_filehost_runtime_ready(reason="plugin_startup")
    assert await ensure_filehost_runtime_ready(reason="playwright_startup")

    require_mock.assert_called_once_with("nonebot_plugin_filehost")
    guard_mock.assert_called_once()
    filehost_url_mock.assert_awaited_once()
    assert filehost_url_mock.await_args is not None
    first_payload = filehost_url_mock.await_args.args[0]
    assert isinstance(first_payload, bytes)
    assert b"filehost-prewarm" in first_payload
    status = get_filehost_prewarm_status()
    assert status["ready"] == "true"
    assert status["url"] == "http://render:9012/filehost/prewarm"
    assert status["last_error"] is None
    assert status["cached_resources"] is not None


@pytest.mark.anyio
async def test_filehost_prewarm_retries_after_failure(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        ensure_filehost_runtime_ready,
        get_filehost_prewarm_status,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    guard_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.ensure_filehost_request_guard_installed",
        return_value=True,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.find_spec",
        return_value=object(),
    )
    require_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.require"
    )
    filehost_url_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.filehost_url",
        new=mocker.AsyncMock(
            side_effect=[
                RuntimeError("bootstrap failed"),
                "http://render:9012/filehost/prewarm",
            ]
        ),
    )

    assert await ensure_filehost_runtime_ready(reason="plugin_startup") is False
    assert get_filehost_prewarm_status()["last_error"] == "bootstrap failed"

    assert await ensure_filehost_runtime_ready(reason="playwright_startup") is True
    assert require_mock.call_count == 2
    assert guard_mock.call_count == 2
    assert filehost_url_mock.await_count == 2
    status = get_filehost_prewarm_status()
    assert status["ready"] == "true"
    assert status["url"] == "http://render:9012/filehost/prewarm"
    assert status["last_error"] is None
    assert status["cached_resources"] is not None


@pytest.mark.anyio
async def test_filehost_prewarm_fails_closed_when_guard_unavailable(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        ensure_filehost_runtime_ready,
        get_filehost_prewarm_status,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.find_spec",
        return_value=object(),
    )
    mocker.patch("nonebot_plugin_htmlrender.resources.filehost.warmup.require")
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.ensure_filehost_request_guard_installed",
        return_value=False,
    )
    filehost_url_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.filehost_url",
        new=mocker.AsyncMock(return_value="http://render:9012/filehost/prewarm"),
    )

    assert await ensure_filehost_runtime_ready(reason="plugin_startup") is False
    filehost_url_mock.assert_not_awaited()
    assert (
        get_filehost_prewarm_status()["last_error"]
        == "filehost request guard is not available for current driver/runtime."
    )


def test_get_filehost_request_headers_uses_device_derived_token(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard._resolve_device_identifier",
        return_value="device-id-123",
    )
    headers = filehost_runtime.get_filehost_request_headers()
    expected = hashlib.sha256(
        b"nonebot-plugin-htmlrender:filehost:guard:v1:device-id-123"
    ).hexdigest()
    assert headers["X-HTMLRender-Filehost-Request"] == expected


def test_get_filehost_request_headers_uses_configured_salt(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")

    cfg = _make_cfg(
        mode="auto",
        remote_policy="filehost",
        filehost_request_header_salt="custom-salt",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=cfg,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard.get_resource_config",
        return_value=cfg,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard._resolve_device_identifier",
        return_value="device-id-123",
    )

    headers = filehost_runtime.get_filehost_request_headers()
    expected = hashlib.sha256(b"custom-salt:device-id-123").hexdigest()
    assert headers["X-HTMLRender-Filehost-Request"] == expected


def test_get_filehost_request_headers_prefers_configured_token(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")

    cfg = _make_cfg(
        mode="auto",
        remote_policy="filehost",
        filehost_request_header_value="configured-token",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=cfg,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard.get_resource_config",
        return_value=cfg,
    )
    resolver = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard._resolve_device_identifier",
        return_value="ignored-device-id",
    )

    headers = filehost_runtime.get_filehost_request_headers()
    assert headers["X-HTMLRender-Filehost-Request"] == "configured-token"
    resolver.assert_not_called()


def test_filehost_guard_token_is_stable_and_recognized(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=_make_cfg(mode="auto", remote_policy="filehost"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard._resolve_device_identifier",
        return_value="device-id-123",
    )
    first = filehost_runtime.get_filehost_request_headers()
    second = filehost_runtime.get_filehost_request_headers()
    generated = first["X-HTMLRender-Filehost-Request"]

    assert generated == second["X-HTMLRender-Filehost-Request"]
    assert filehost_runtime._is_valid_guard_token(generated)
    assert not filehost_runtime._is_valid_guard_token("invalid-token")


def test_resolve_device_identifier_falls_back_to_process_uuid(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard.import_module",
        side_effect=RuntimeError("machineid unavailable"),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.guard.uuid.getnode",
        side_effect=RuntimeError("mac unavailable"),
    )

    fallback = filehost_runtime._resolve_device_identifier()
    assert fallback == filehost_runtime._FILEHOST_FALLBACK_INSTANCE_ID


@pytest.mark.anyio
async def test_filehost_url_reuses_cached_path_mapping(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    filehost_runtime._FILEHOST_PATH_INDEX.clear()

    asset = tmp_path / "style.css"
    asset.write_text("body{}", encoding="utf-8")

    upload_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.cache._filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/style.css"),
    )

    first = await filehost_runtime.filehost_url(asset)
    second = await filehost_runtime.filehost_url(asset)

    assert first == second == "http://render/filehost/style.css"
    upload_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_filehost_directory_prewarm_skips_template_files(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")
    filehost_runtime._FILEHOST_REGISTERED_ROOTS.clear()
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    filehost_runtime._FILEHOST_PATH_INDEX.clear()

    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "card.html").write_text("<html/>", encoding="utf-8")
    (assets / "site.css").write_text("body{}", encoding="utf-8")

    cfg = _make_cfg(
        mode="auto",
        remote_policy="filehost",
        is_remote_mode=True,
        filehost_allowed_paths=[assets],
        filehost_prewarm_enabled=True,
        filehost_prewarm_max_files=16,
        filehost_prewarm_extensions=[".css", ".html"],
        filehost_prewarm_paths=[assets],
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.get_resource_config",
        return_value=cfg,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.get_resource_config",
        return_value=cfg,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.find_spec",
        return_value=object(),
    )
    mocker.patch("nonebot_plugin_htmlrender.resources.filehost.warmup.require")
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.warmup.ensure_filehost_request_guard_installed",
        return_value=True,
    )
    snapshot_spy = mocker.spy(
        import_module("nonebot_plugin_htmlrender.resources.filehost.cache"),
        "_read_consistent_path_snapshot",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.cache._filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/resource"),
    )

    assert await filehost_runtime.ensure_filehost_runtime_ready(reason="unit")
    uploaded_names = [Path(call.args[0]).name for call in snapshot_spy.call_args_list]
    assert "site.css" in uploaded_names
    assert "card.html" not in uploaded_names


@pytest.mark.anyio
async def test_filehost_lease_ref_count_and_ttl_prune(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    filehost_runtime = import_module("nonebot_plugin_htmlrender.resources.filehost")
    filehost_runtime._FILEHOST_RESOURCE_CACHE.clear()
    filehost_runtime._FILEHOST_RESOURCE_INFLIGHT.clear()
    filehost_runtime._FILEHOST_PATH_INDEX.clear()
    filehost_runtime._FILEHOST_LEASES.clear()

    asset = tmp_path / "logo.png"
    asset.write_bytes(b"logo")
    mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.cache.get_resource_config",
        return_value=_make_cfg(
            mode="auto",
            remote_policy="filehost",
            filehost_cache_ttl_seconds=0.01,
        ),
    )
    upload_mock = mocker.patch(
        "nonebot_plugin_htmlrender.resources.filehost.cache._filehost_upload",
        new=mocker.AsyncMock(return_value="http://render/filehost/logo.png"),
    )

    lease = filehost_runtime.create_filehost_lease()
    url = await filehost_runtime.filehost_url(asset, lease_id=lease)
    assert url == "http://render/filehost/logo.png"
    assert upload_mock.await_count == 1
    assert len(filehost_runtime._FILEHOST_RESOURCE_CACHE) == 1
    entry = next(iter(filehost_runtime._FILEHOST_RESOURCE_CACHE.values()))
    assert entry["lease_ref_count"] == 1
    assert entry["mapping_expires_at_ns"] is None

    await filehost_runtime.release_filehost_lease(lease)
    entry_after_release = next(iter(filehost_runtime._FILEHOST_RESOURCE_CACHE.values()))
    assert entry_after_release["lease_ref_count"] == 0
    assert entry_after_release["mapping_expires_at_ns"] is not None

    await asyncio.sleep(0.02)
    await filehost_runtime.prune_filehost_cache()
    assert filehost_runtime._FILEHOST_RESOURCE_CACHE == {}
