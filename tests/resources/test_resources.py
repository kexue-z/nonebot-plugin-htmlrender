from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.rendering.errors import (
    InvalidRenderRequest,
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceCacheSettings,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    PackageResourceRef,
    ResourceContent,
    ResourceRef,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from collections.abc import Mapping


def _published_label(value: str | Path | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value).rsplit("/", maxsplit=1)[-1]


class RecordingPublisher:
    def __init__(self, *, prefix: str = "https://assets.example/") -> None:
        self.prefix = prefix
        self.published: list[tuple[str | Path | bytes, str | None, str | None]] = []
        self.released: list[str] = []
        self.started = 0
        self.closed = 0
        self._next_lease = 0

    def create_lease(self) -> str:
        self._next_lease += 1
        return f"lease:{self._next_lease}"

    async def release(self, lease_id: str) -> None:
        self.released.append(lease_id)

    def request_headers(self) -> Mapping[str, str]:
        return {"X-Test-Asset": "token"}

    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> str:
        self.published.append((value, lease_id, suffix))
        return f"{self.prefix}{_published_label(value)}"

    async def startup(self) -> None:
        self.started += 1

    async def clear(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed += 1


class RecordingReader:
    def __init__(self, content: ResourceContent) -> None:
        self.content = content
        self.invalidated: list[object] = []
        self.clears = 0
        self.reads = 0

    async def read(self, reference: ResourceRef) -> ResourceContent:
        del reference
        self.reads += 1
        return self.content

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        del reference
        return self.content.revision

    async def invalidate(self, reference: ResourceRef) -> None:
        self.invalidated.append(reference.cache_key)

    async def clear(self) -> None:
        self.clears += 1


class ConcurrentResolver:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = anyio.Lock()

    async def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> str:
        async with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        await anyio.sleep(0.01)
        async with self.lock:
            self.active -= 1
        name = value.name if isinstance(value, Path) else str(value)
        base = template_base.name if template_base is not None else "none"
        return f"resolved:{base}:{name}"


class FailingResolver:
    async def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> object:
        del value, template_base
        raise RuntimeError("resolver unavailable")


class UnhashableResolver:
    def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> object:
        del value, template_base
        return []


def _resources(
    tmp_path: Path,
    *,
    strategy: ResourceStrategy | None = None,
    publisher: RecordingPublisher | None = None,
) -> ResourceService:
    return ResourceService(
        reader=build_resource_reader(
            ResourceCacheSettings(revalidate_seconds=60),
            NoopCacheObserver(),
            AnyioWorkerExecutor(),
        ),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(tmp_path,),
            allow_any=False,
        ),
        strategy=strategy or ResourceStrategy(),
        publisher=publisher,
    )


@pytest.mark.anyio
async def test_read_api_accepts_concrete_resource_references(tmp_path: Path) -> None:
    path = tmp_path / "resource.txt"
    path.write_text("filesystem", encoding="utf-8")
    resources = _resources(tmp_path)

    assert await resources.read_text(path) == "filesystem"
    assert await resources.read_bytes(FileResourceRef(path)) == b"filesystem"
    assert await resources.read_text(InlineResourceRef("内联".encode())) == "内联"
    assert "{{ text" in await resources.read_text(
        PackageResourceRef(
            "nonebot_plugin_htmlrender",
            "templates/text/text.html",
        )
    )


@pytest.mark.anyio
async def test_reader_translates_package_and_decode_failures(tmp_path: Path) -> None:
    resources = _resources(tmp_path)

    with pytest.raises(ResourceResolutionError, match="Could not read resource"):
        await resources.read_bytes(
            PackageResourceRef("missing_package_xyz", "file.txt")
        )
    with pytest.raises(ResourceResolutionError, match="Could not decode resource"):
        await resources.read_text(InlineResourceRef(b"\xff"))


@pytest.mark.anyio
async def test_read_refresh_invalidates_only_the_injected_reader(
    tmp_path: Path,
) -> None:
    reference = InlineResourceRef(b"key")
    reader = RecordingReader(
        ResourceContent(b"value", "text/plain", ResourceRevision("one"))
    )
    other = RecordingReader(
        ResourceContent(b"other", "text/plain", ResourceRevision("two"))
    )
    local_access = ConfiguredLocalAccessPolicy(
        allowed_roots=(tmp_path,),
        allow_any=False,
    )
    resources = ResourceService(
        reader=reader,
        local_access=local_access,
        strategy=ResourceStrategy(),
    )
    other_resources = ResourceService(
        reader=other,
        local_access=local_access,
        strategy=ResourceStrategy(),
    )

    assert await resources.read_bytes(reference, refresh=True) == b"value"
    await resources.clear()

    assert reader.invalidated == [reference.cache_key]
    assert reader.clears == 1
    assert other.invalidated == []
    assert other.clears == 0
    assert await other_resources.read_bytes(reference) == b"other"


@pytest.mark.anyio
async def test_local_file_strategy_resolves_nested_values(tmp_path: Path) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    image = template_root / "logo.png"
    image.write_bytes(b"image")
    resources = _resources(tmp_path)

    result = await resources.resolve_template_vars(
        {
            "path": image,
            "relative": "logo.png",
            "nested": [image, (image,), {image}],
            "plain": "hello world",
        },
        template_base=template_root,
    )

    expected = image.resolve().as_uri()
    assert result == {
        "path": expected,
        "relative": expected,
        "nested": [expected, (expected,), {expected}],
        "plain": "hello world",
    }
    assert await resources.to_resource_url(image) == expected


@pytest.mark.anyio
async def test_resolve_mode_off_requires_an_explicit_override(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.OFF),
    )

    values = {"asset": asset}
    assert await resources.resolve_template_vars(values) == values
    assert await resources.resolve_template_vars(values, resolver="file") == {
        "asset": asset.as_uri()
    }


@pytest.mark.anyio
async def test_remote_memory_and_error_strategies_are_explicit(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")
    memory = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.MEMORY,
        ),
    )
    denied = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.ERROR,
        ),
    )

    values = {"path": asset, "bytes": b"asset"}
    assert await memory.resolve_template_vars(values) == values
    with pytest.raises(ResourceResolutionError, match="disabled"):
        await denied.resolve_template_vars(values)


@pytest.mark.anyio
async def test_filehost_policy_uses_injected_publisher_and_access_policy(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    asset = template_root / "asset.bin"
    asset.write_bytes(b"asset")
    publisher = RecordingPublisher()
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        publisher=publisher,
    )

    lease = publisher.create_lease()
    result = await resources.resolve_template_vars(
        {
            "absolute": asset,
            "relative": "asset.bin",
            "bytes": b"raw",
            "buffer": BytesIO(b"buffer"),
            "mutable": bytearray(b"mutable"),
        },
        template_base=template_root,
        lease_id=lease,
    )

    assert result == {
        "absolute": "https://assets.example/asset.bin",
        "relative": "https://assets.example/asset.bin",
        "bytes": "https://assets.example/raw",
        "buffer": "https://assets.example/buffer",
        "mutable": "https://assets.example/mutable",
    }
    assert len(publisher.published) == 5
    assert publisher.published.count((asset.resolve(), lease, None)) == 2
    assert (b"raw", lease, None) in publisher.published
    assert (b"buffer", lease, None) in publisher.published
    assert (b"mutable", lease, None) in publisher.published


@pytest.mark.anyio
async def test_filehost_policy_rejects_outside_paths_in_strict_mode(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    asset = outside / "secret.bin"
    asset.write_bytes(b"secret")
    publisher = RecordingPublisher()
    resources = ResourceService(
        reader=RecordingReader(ResourceContent(b"unused")),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(allowed,),
            allow_any=False,
        ),
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        publisher=publisher,
    )

    assert await resources.resolve_template_vars({"asset": asset}) == {"asset": asset}
    with pytest.raises(ResourceResolutionError, match="outside allowed roots"):
        await resources.resolve_template_vars({"asset": asset}, strict=True)
    assert publisher.published == []


@pytest.mark.anyio
async def test_explicit_tolerant_resolution_overrides_strict_strategy(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    asset = outside / "secret.bin"
    asset.write_bytes(b"secret")
    resources = ResourceService(
        reader=RecordingReader(ResourceContent(b"unused")),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(allowed,),
            allow_any=False,
        ),
        strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.STRICT),
    )

    with pytest.raises(ResourceResolutionError, match="outside allowed roots"):
        await resources.resolve_template_vars({"asset": asset})
    assert await resources.resolve_template_vars(
        {"asset": asset},
        strict=False,
    ) == {"asset": asset}


@pytest.mark.anyio
async def test_filehost_policy_requires_an_injected_publisher(tmp_path: Path) -> None:
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
    )

    with pytest.raises(ResourceResolutionError, match="requires an AssetPublisher"):
        await resources.resolve_template_vars({"asset": b"value"}, strict=True)


@pytest.mark.anyio
async def test_custom_resolver_runs_recursively_and_concurrently(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    paths = [template_root / f"{index}.bin" for index in range(8)]
    resolver = ConcurrentResolver()
    resources = _resources(tmp_path)

    result = await resources.resolve_template_vars(
        {"paths": paths},
        template_base=template_root,
        resolver=resolver,
    )

    assert result == {
        "paths": [f"resolved:templates:{index}.bin" for index in range(8)]
    }
    assert resolver.max_active > 1


@pytest.mark.anyio
async def test_custom_resolver_failure_is_soft_unless_strict(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    resources = _resources(tmp_path)

    assert await resources.resolve_template_vars(
        {"asset": asset},
        resolver=FailingResolver(),
    ) == {"asset": asset}
    with pytest.raises(ResourceResolutionError, match="resolver unavailable"):
        await resources.resolve_template_vars(
            {"asset": asset},
            resolver=FailingResolver(),
            strict=True,
        )


@pytest.mark.anyio
async def test_unknown_or_malformed_resolvers_fail_at_the_boundary(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "asset.bin"
    resources = _resources(tmp_path)

    with pytest.raises(InvalidRenderRequest, match="Unknown resource policy"):
        await resources.resolve_template_vars({"asset": asset}, resolver="missing")
    with pytest.raises(InvalidRenderRequest, match=r"must expose resolve\(\)"):
        await resources.resolve_template_vars({"asset": asset}, resolver=object())


async def test_resource_path_normalization_uses_stable_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources(tmp_path)
    path_type = type(tmp_path)
    original_expanduser = path_type.expanduser

    def expanduser(path: Path) -> Path:
        if str(path) == "broken-path":
            raise RuntimeError("home directory is unavailable")
        return original_expanduser(path)

    monkeypatch.setattr(path_type, "expanduser", expanduser)

    with pytest.raises(ResourceResolutionError, match="normalize resource path"):
        await resources.read_bytes("broken-path")
    with pytest.raises(ResourceResolutionError, match="normalize template base"):
        await resources.resolve_template_vars({}, template_base="broken-path")


async def test_custom_resolver_set_items_must_remain_hashable(
    tmp_path: Path,
) -> None:
    resources = _resources(tmp_path)

    with pytest.raises(ResourceResolutionError, match="remain hashable"):
        await resources.resolve_template_vars(
            {"values": {b"value"}},
            resolver=UnhashableResolver(),
            strict=True,
        )


@pytest.mark.anyio
async def test_url_token_resolution_preserves_external_urls_query_and_fragment(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "style.css").write_text("body{}", encoding="utf-8")
    resources = _resources(tmp_path)

    result = await resources.resolve_url_tokens(
        [
            "style.css?v=1#theme",
            "https://cdn.example/site.css?v=2",
            "data:text/plain,hello",
            "#section",
        ],
        template_base=root,
    )

    assert result == [
        f"{(root / 'style.css').as_uri()}?v=1#theme",
        "https://cdn.example/site.css?v=2",
        "data:text/plain,hello",
        "#section",
    ]


@pytest.mark.anyio
async def test_url_token_resolution_translates_invalid_urls(tmp_path: Path) -> None:
    resources = _resources(tmp_path)

    with pytest.raises(ResourceResolutionError, match="Invalid resource URL"):
        await resources.resolve_url_tokens(["http://["])


@pytest.mark.anyio
async def test_service_instances_can_select_opposite_transport_strategies(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")
    local = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            local_local_policy=LocalLocalResourcePolicy.FILE,
        ),
    )
    remote = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.MEMORY,
        ),
    )

    assert await local.resolve_template_vars({"asset": asset}) == {
        "asset": asset.as_uri()
    }
    assert await remote.resolve_template_vars({"asset": asset}) == {"asset": asset}
    assert local.strategy.is_remote is False
    assert remote.strategy.is_remote is True
