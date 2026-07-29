"""ResourceService policy, traversal, publication, and resolution tests."""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.rendering.errors import (
    InvalidRenderRequest,
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.resources._traversal import ResourceTraversalBudget
from nonebot_plugin_htmlrender.resources.config import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceCacheSettings,
    ResourceResolveMode,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    NotModified,
    PackageResourceRef,
    PublishedResource,
    ResourceContent,
    ResourceRef,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pytest_mock import MockerFixture


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

    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> PublishedResource:
        self.published.append((value, lease_id, suffix))
        return PublishedResource(
            url=f"{self.prefix}{_published_label(value)}",
            request_headers={"X-Test-Asset": "token"},
        )

    async def startup(self) -> None:
        self.started += 1

    async def clear(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed += 1


class ConflictingPublisher(RecordingPublisher):
    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> PublishedResource:
        self.published.append((value, lease_id, suffix))
        return PublishedResource(
            url="https://assets.example/shared",
            request_headers={"X-Test-Asset": _published_label(value)},
        )


class RecordingReader:
    def __init__(self, content: ResourceContent) -> None:
        self.content = content
        self.invalidated: list[object] = []
        self.clears = 0
        self.reads = 0
        self.refreshes: list[bool] = []

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        del reference
        self.reads += 1
        self.refreshes.append(refresh)
        return self.content

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent | NotModified:
        if self.content.revision == revision:
            return NotModified(revision)
        return await self.read(reference)

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
        self.calls = 0
        self.max_active = 0
        self.lock = anyio.Lock()

    async def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> str:
        async with self.lock:
            self.calls += 1
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


class DeceptiveMapping(Mapping[str, object]):
    """Mapping whose length deliberately understates its iterable contents."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return 0


def _resources(
    tmp_path: Path,
    *,
    strategy: ResourceStrategy | None = None,
    publisher: RecordingPublisher | None = None,
    traversal_budget: ResourceTraversalBudget | None = None,
) -> ResourceService:
    return ResourceService(
        reader=build_resource_reader(
            ResourceCacheSettings(revalidate_seconds=60),
            NoopCacheObserver(),
            AnyioWorkerExecutor(),
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(tmp_path,),
            allow_any=False,
        ),
        strategy=strategy or ResourceStrategy(),
        publisher=publisher,
        traversal_budget=traversal_budget,
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
async def test_read_refresh_is_forwarded_only_to_the_injected_reader(
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

    assert reader.refreshes == [True]
    assert reader.invalidated == []
    assert reader.clears == 1
    assert other.invalidated == []
    assert other.clears == 0
    assert await other_resources.read_bytes(reference) == b"other"
    assert other.refreshes == [False]


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
            "relative": "./logo.png",
            "bare_text": "logo.png",
            "nested": [image, (image,), {image}],
            "plain": "hello world",
        },
        template_base=template_root,
    )

    expected = image.resolve().as_uri()
    assert result.value == {
        "path": expected,
        "relative": expected,
        "bare_text": "logo.png",
        "nested": [expected, (expected,), {expected}],
        "plain": "hello world",
    }
    assert (await resources.to_resource_url(image)).value == expected
    assert result.request_headers_by_url == {}


@pytest.mark.anyio
async def test_plain_text_classification_never_probes_the_filesystem(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    (template_root / "looks-like-file.png").write_bytes(b"x")
    resources = _resources(tmp_path)

    exists_spy = mocker.spy(Path, "exists")
    result = await resources.resolve_template_vars(
        {"caption": "looks-like-file.png", "plain": "hello world"},
        template_base=template_root,
    )

    assert result.value == {
        "caption": "looks-like-file.png",
        "plain": "hello world",
    }
    assert exists_spy.call_count == 0


@pytest.mark.anyio
async def test_resolve_mode_off_requires_an_explicit_override(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.OFF),
    )

    values = {"asset": asset}
    assert (await resources.resolve_template_vars(values)).value == values
    assert (await resources.resolve_template_vars(values, resolver="file")).value == {
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
    assert (await memory.resolve_template_vars(values)).value == values
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
            "relative": "./asset.bin",
            "bytes": b"raw",
            "buffer": BytesIO(b"buffer"),
            "mutable": bytearray(b"mutable"),
        },
        template_base=template_root,
        lease_id=lease,
    )

    assert result.value == {
        "absolute": "https://assets.example/asset.bin",
        "relative": "https://assets.example/asset.bin",
        "bytes": "https://assets.example/raw",
        "buffer": "https://assets.example/buffer",
        "mutable": "https://assets.example/mutable",
    }
    assert result.request_headers_by_url == {
        "https://assets.example/asset.bin": {"X-Test-Asset": "token"},
        "https://assets.example/buffer": {"X-Test-Asset": "token"},
        "https://assets.example/mutable": {"X-Test-Asset": "token"},
        "https://assets.example/raw": {"X-Test-Asset": "token"},
    }
    assert len(publisher.published) == 5
    assert publisher.published.count((asset.resolve(), lease, None)) == 2
    assert (b"raw", lease, None) in publisher.published
    assert (b"buffer", lease, None) in publisher.published
    assert (b"mutable", lease, None) in publisher.published


@pytest.mark.anyio
async def test_filehost_single_url_carries_exact_request_headers(
    tmp_path: Path,
) -> None:
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        publisher=RecordingPublisher(),
    )

    result = await resources.to_resource_url(b"single")

    assert result.value == "https://assets.example/single"
    assert result.request_headers_by_url == {result.value: {"X-Test-Asset": "token"}}


@pytest.mark.anyio
async def test_filehost_rejects_conflicting_capabilities_for_one_url(
    tmp_path: Path,
) -> None:
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        publisher=ConflictingPublisher(),
    )

    with pytest.raises(ResourceResolutionError, match="conflicting authorization"):
        await resources.resolve_template_vars(
            {"first": b"first", "second": b"second"},
            strict=False,
        )


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

    assert (await resources.resolve_template_vars({"asset": asset})).value == {
        "asset": asset
    }
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
    assert (
        await resources.resolve_template_vars(
            {"asset": asset},
            strict=False,
        )
    ).value == {"asset": asset}


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

    assert result.value == {
        "paths": [f"resolved:templates:{index}.bin" for index in range(8)]
    }
    assert resolver.max_active > 1


@pytest.mark.anyio
async def test_resource_traversal_concurrency_is_shared_across_calls(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / f"{index}.bin" for index in range(12)]
    resolver = ConcurrentResolver()
    resources = _resources(
        tmp_path,
        traversal_budget=ResourceTraversalBudget(max_concurrency=2),
    )
    results: list[object] = []

    async def resolve(values: list[Path]) -> None:
        result = await resources.resolve_template_vars(
            {"paths": values},
            resolver=resolver,
        )
        results.append(result.value)

    async with anyio.create_task_group() as group:
        group.start_soon(resolve, paths[:6])
        group.start_soon(resolve, paths[6:])

    assert len(results) == 2
    assert resolver.calls == len(paths)
    assert resolver.max_active == 2


@pytest.mark.anyio
async def test_resource_traversal_allows_repeated_non_cyclic_containers(
    tmp_path: Path,
) -> None:
    resolver = ConcurrentResolver()
    resources = _resources(tmp_path)
    shared = [tmp_path / "asset.bin"]

    result = await resources.resolve_template_vars(
        {"left": shared, "right": shared},
        resolver=resolver,
    )

    expected = ["resolved:none:asset.bin"]
    assert result.value == {"left": expected, "right": expected}
    assert resolver.calls == 2


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["nodes", "deceptive", "depth", "cycle"])
async def test_resource_traversal_rejects_invalid_trees_before_io(
    tmp_path: Path,
    failure: str,
) -> None:
    resolver = ConcurrentResolver()
    value: Mapping[str, object]
    if failure == "nodes":
        budget = ResourceTraversalBudget(max_nodes=3)
        value = {"assets": [tmp_path / "one.bin", tmp_path / "two.bin"]}
        message = "node traversal limit"
    elif failure == "deceptive":
        budget = ResourceTraversalBudget(max_nodes=2)
        value = DeceptiveMapping(
            {
                "one": tmp_path / "one.bin",
                "two": tmp_path / "two.bin",
            }
        )
        message = "node traversal limit"
    elif failure == "depth":
        budget = ResourceTraversalBudget(max_depth=1)
        value = {"assets": [[tmp_path / "asset.bin"]]}
        message = "depth limit"
    else:
        budget = ResourceTraversalBudget()
        cyclic: list[object] = []
        cyclic.append(cyclic)
        value = {"assets": cyclic}
        message = "contains a cycle"
    resources = _resources(tmp_path, traversal_budget=budget)

    with pytest.raises(ResourceResolutionError, match=message):
        await resources.resolve_template_vars(
            value,
            resolver=resolver,
        )

    assert resolver.calls == 0


@pytest.mark.parametrize(
    ("field", "factory"),
    [
        ("max_nodes", lambda: ResourceTraversalBudget(max_nodes=0)),
        ("max_depth", lambda: ResourceTraversalBudget(max_depth=-1)),
        ("max_concurrency", lambda: ResourceTraversalBudget(max_concurrency=0)),
        ("max_nodes", lambda: ResourceTraversalBudget(max_nodes=True)),
    ],
)
def test_resource_traversal_budget_rejects_invalid_values(
    field: str,
    factory: Callable[[], ResourceTraversalBudget],
) -> None:
    with pytest.raises(ValueError, match=field):
        factory()


@pytest.mark.anyio
async def test_custom_resolver_failure_is_soft_unless_strict(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    resources = _resources(tmp_path)

    assert (
        await resources.resolve_template_vars(
            {"asset": asset},
            resolver=FailingResolver(),
        )
    ).value == {"asset": asset}
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

    assert result.value == [
        f"{(root / 'style.css').as_uri()}?v=1#theme",
        "https://cdn.example/site.css?v=2",
        "data:text/plain,hello",
        "#section",
    ]


@pytest.mark.anyio
async def test_filehost_url_token_authorization_uses_the_final_url(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "style.css").write_text("body{}", encoding="utf-8")
    resources = _resources(
        tmp_path,
        strategy=ResourceStrategy(
            is_remote=True,
            remote_local_policy=RemoteLocalResourcePolicy.FILEHOST,
        ),
        publisher=RecordingPublisher(),
    )

    result = await resources.resolve_url_tokens(
        ["style.css?v=1#theme"],
        template_base=root,
    )

    expected = "https://assets.example/style.css?v=1#theme"
    assert result.value == [expected]
    assert result.request_headers_by_url == {expected: {"X-Test-Asset": "token"}}


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

    assert (await local.resolve_template_vars({"asset": asset})).value == {
        "asset": asset.as_uri()
    }
    assert (await remote.resolve_template_vars({"asset": asset})).value == {
        "asset": asset
    }
    assert local.strategy.is_remote is False
    assert remote.strategy.is_remote is True
