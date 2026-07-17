from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    PackageResourceRef,
    RemoteResourceRef,
    ResourceContent,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.source import (
    FilesystemResourceSource,
    PackageResourceSource,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_resource_models_have_stable_structural_cache_keys(tmp_path: Path) -> None:
    path = tmp_path / "folder" / ".." / "asset.css"
    file_reference = FileResourceRef(path)
    package_reference = PackageResourceRef("example_package", "assets/card.css")
    remote_reference = RemoteResourceRef("https://assets.example/card.css?v=1")
    inline_reference = InlineResourceRef(b"card", "text/css")

    assert file_reference.path == path.resolve()
    assert file_reference.cache_key == ("file", str(path.resolve()))
    assert package_reference.cache_key == (
        "package",
        "example_package",
        "assets/card.css",
    )
    assert remote_reference.cache_key == (
        "remote",
        "https://assets.example/card.css?v=1",
    )
    assert inline_reference.cache_key == (
        "inline",
        sha256(b"card").digest(),
        4,
        "text/css",
    )
    assert ResourceContent(
        b"card",
        "text/css",
        ResourceRevision("revision"),
    ).revision == ResourceRevision("revision")


def test_inline_resource_rejects_mutable_payloads() -> None:
    with pytest.raises(TypeError, match="immutable bytes"):
        InlineResourceRef(cast("bytes", bytearray(b"mutable")))


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "/absolute.css", "assets/../secret.css"],
)
def test_package_reference_rejects_non_logical_names(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid logical resource name"):
        PackageResourceRef("example_package", name)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "data:text/plain,secret", "relative/file.css", "https:"],
)
def test_remote_reference_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(ValueError, match="http:// or https://"):
        RemoteResourceRef(url)


def test_package_source_builds_logical_references() -> None:
    source = PackageResourceSource("example_package", "assets/styles")

    assert source.identity == ("package", "example_package", "assets/styles")
    assert source.resource("themes/light.css") == PackageResourceRef(
        "example_package",
        "assets/styles/themes/light.css",
    )
    with pytest.raises(ValueError, match="Invalid logical resource name"):
        source.resource("../secret.css")


def test_filesystem_source_canonicalizes_and_contains_resources(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    root.mkdir()
    source = FilesystemResourceSource(root / ".")

    assert source.root == root.resolve()
    assert source.identity == ("filesystem", str(root.resolve()))
    assert (
        source.resource("nested/card.html") == (root / "nested" / "card.html").resolve()
    )
    with pytest.raises(ValueError, match="Invalid logical resource name"):
        source.resource("../outside.html")


def test_filesystem_source_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    source = FilesystemResourceSource(root)

    with pytest.raises(ValueError, match="escapes filesystem root"):
        source.resource("linked/secret.txt")
