from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any

import pytest

from nonebot_plugin_htmlrender import resources
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.resources import ResourceResolveError
from nonebot_plugin_htmlrender.resources import resolve as _resolve_mod
from nonebot_plugin_htmlrender.resources import template as _template_mod
from nonebot_plugin_htmlrender.resources.config import ResourceConfig

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_resolve_template_vars_sequence_tuple_set_and_bytesio(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    asset = tmp_path / "a.txt"
    asset.write_text("x", encoding="utf-8")
    mocker.patch.object(
        _resolve_mod,
        "get_resource_config",
        return_value=ResourceConfig(
            resource_resolve_mode=ResourceResolveMode.AUTO,
            remote_local_resource_policy=RemoteLocalResourcePolicy.PASSTHROUGH,
            local_local_resource_policy=LocalLocalResourcePolicy.FILE,
            filehost_allow_any_path=True,
        ),
    )

    data = {
        "tuple": ("./a.txt",),
        "list": ["./a.txt"],
        "set": {"./a.txt"},
        "seq": range(2),
        "bytes_io": BytesIO(b"abc"),
    }
    resolved = await resources.resolve_template_vars(
        data, template_base=tmp_path, resolver="auto"
    )
    assert resolved["tuple"][0].startswith("file://")
    assert resolved["list"][0].startswith("file://")
    assert any(str(v).startswith("file://") for v in resolved["set"])
    assert resolved["seq"] == [0, 1]
    assert isinstance(resolved["bytes_io"], BytesIO)


@pytest.mark.anyio
async def test_to_resource_url_raises_when_result_not_string(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        _template_mod, "_resolve_any", new=mocker.AsyncMock(return_value=123)
    )
    with pytest.raises(ResourceResolveError, match="Resolved resource is not URL text"):
        await resources.to_resource_url("x")


def test_pick_policy_and_template_base_validation(mocker: MockerFixture) -> None:
    cfg = ResourceConfig(
        is_remote_mode=True,
        resource_resolve_mode=ResourceResolveMode.AUTO,
        remote_local_resource_policy=RemoteLocalResourcePolicy.FILEHOST,
        local_local_resource_policy=LocalLocalResourcePolicy.FILE,
    )
    mocker.patch.object(_resolve_mod, "get_resource_config", return_value=cfg)
    assert _resolve_mod._pick_policy("auto") == "filehost"
    assert _resolve_mod._normalize_template_base("  ") is None
    assert _resolve_mod._is_local_path_string("a/b", None) is True
    with pytest.raises(ValueError, match="resource_resolver"):
        _resolve_mod._pick_policy("invalid")


@pytest.mark.anyio
async def test_resolve_scalar_resource_error_policy_and_strict(
    mocker: MockerFixture,
) -> None:
    cfg = ResourceConfig(
        is_remote_mode=True,
        resource_resolve_mode=ResourceResolveMode.AUTO,
        remote_local_resource_policy=RemoteLocalResourcePolicy.ERROR,
    )
    mocker.patch.object(_resolve_mod, "get_resource_config", return_value=cfg)

    with pytest.raises(ResourceResolveError, match="Local resources are not allowed"):
        await _resolve_mod._resolve_scalar_resource(
            "./x", template_base=None, strict=True, resolver="auto"
        )

    result = await _resolve_mod._resolve_scalar_resource(
        "./x", template_base=None, strict=False, resolver="auto"
    )
    assert result == "./x"


@pytest.mark.anyio
async def test_resolve_html_resources_and_should_resolve_short_circuit(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch.object(_template_mod, "_should_resolve", return_value=False)
    html = '<img src="./x.png">'
    assert await resources.resolve_html_resources(html, template_base=tmp_path) == html

    mocker.patch.object(_template_mod, "_should_resolve", return_value=True)
    mocker.patch.object(
        _template_mod,
        "_resolve_html_attr_resources",
        new=mocker.AsyncMock(return_value="a"),
    )
    mocker.patch.object(
        _template_mod,
        "_resolve_css_url_resources",
        new=mocker.AsyncMock(return_value="b"),
    )
    assert await resources.resolve_html_resources(html, template_base=tmp_path) == "b"


def test_resource_helpers_path_and_policy_branches(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    cfg = ResourceConfig(
        resource_resolve_mode=ResourceResolveMode.AUTO,
        remote_local_resource_policy=RemoteLocalResourcePolicy.PASSTHROUGH,
        local_local_resource_policy=LocalLocalResourcePolicy.FILE,
    )
    mocker.patch.object(_resolve_mod, "get_resource_config", return_value=cfg)

    normalized_base = _resolve_mod._normalize_template_base(str(tmp_path))
    assert normalized_base is not None
    assert normalized_base.is_dir()
    assert _resolve_mod._is_local_path_string("", None) is False
    assert _resolve_mod._is_local_path_string("https://example.com/a", None) is False
    assert _resolve_mod._is_local_path_string("C:\\a\\b", None) is True

    abs_path = (tmp_path / "a.txt").resolve()
    abs_path.write_text("x", encoding="utf-8")
    assert _resolve_mod._resolve_local_path(abs_path) == abs_path
    assert _resolve_mod._resolve_local_path("a.txt", template_base=tmp_path) == abs_path

    with pytest.raises(resources.ResourceResolveError, match="without an allowed root"):
        _resolve_mod._validate_filehost_path_allowed(abs_path, template_base=None)

    class _CustomResolver:
        async def resolve(self, value, *, template_base=None):  # noqa: ARG002
            return value

    assert _resolve_mod._pick_policy(_CustomResolver()) == "custom"
    assert _resolve_mod._should_resolve(_CustomResolver()) is True
    assert _resolve_mod._should_resolve("filehost") is True

    invalid_resolver: Any = object()
    with pytest.raises(ValueError, match="custom object must expose"):
        _resolve_mod._pick_policy(invalid_resolver)


@pytest.mark.anyio
async def test_resolve_scalar_and_url_token_branches(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    cfg = ResourceConfig(
        resource_resolve_mode=ResourceResolveMode.AUTO,
        remote_local_resource_policy=RemoteLocalResourcePolicy.PASSTHROUGH,
        local_local_resource_policy=LocalLocalResourcePolicy.PASSTHROUGH,
        filehost_allow_any_path=True,
    )
    mocker.patch.object(_resolve_mod, "get_resource_config", return_value=cfg)

    class _CustomResolver:
        async def resolve(self, value, *, template_base=None):  # noqa: ARG002
            if isinstance(value, bytes):
                return "bytes://ok"
            return "custom://ok"

    assert (
        await _resolve_mod._resolve_scalar_resource(
            "http://example.com/x",
            template_base=tmp_path,
            strict=False,
            resolver="auto",
        )
        == "http://example.com/x"
    )
    assert (
        await _resolve_mod._resolve_scalar_resource(
            "x", template_base=tmp_path, strict=False, resolver=_CustomResolver()
        )
        == "custom://ok"
    )
    assert (
        await _resolve_mod._resolve_scalar_resource(
            bytearray(b"a"), template_base=tmp_path, strict=False, resolver="filehost"
        )
        == b"a"
    )
    assert (
        await _resolve_mod._resolve_scalar_resource(
            BytesIO(b"b"), template_base=tmp_path, strict=False, resolver="filehost"
        )
        == b"b"
    )

    mocker.patch.object(_resolve_mod, "_pick_policy", return_value="unknown-policy")
    with pytest.raises(resources.ResourceResolveError):
        await _resolve_mod._resolve_scalar_resource(
            "./x", template_base=tmp_path, strict=True, resolver="auto"
        )

    mocker.patch.object(_resolve_mod, "_pick_policy", return_value="passthrough")
    assert (
        await _resolve_mod._resolve_url_token(
            "", template_base=tmp_path, strict=False, resolver="auto"
        )
        == ""
    )
    assert (
        await _resolve_mod._resolve_url_token(
            "https://example.com/x",
            template_base=tmp_path,
            strict=False,
            resolver="auto",
        )
        == "https://example.com/x"
    )

    assert _resolve_mod._extract_local_candidate("https://example.com/x") is None
    assert _resolve_mod._extract_local_candidate("a/b?x=1#f") == ("a/b", "x=1", "f")

    mocker.patch.object(
        _resolve_mod, "_resolve_scalar_resource", new=mocker.AsyncMock(return_value=123)
    )
    assert (
        await _resolve_mod._resolve_url_token(
            "a/b", template_base=tmp_path, strict=False, resolver="auto"
        )
        == "a/b"
    )
