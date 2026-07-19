from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest

from nonebot_plugin_htmlrender.adapters.htmlkit.document import (
    build_htmlkit_document,
)
from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
)
from nonebot_plugin_htmlrender.preparation import PreparedAsset, prepare_html
from nonebot_plugin_htmlrender.resources import (
    ResourceNotFound,
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot_plugin_htmlrender.resources.models import (
        ResourceContent,
        ResourceRef,
        ResourceRevision,
    )


def _resources(
    root: Path,
) -> ResourceService:
    worker = AnyioWorkerExecutor()
    reader = CompositeResourceReader(
        worker,
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
    )
    return ResourceService(
        reader=reader,
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(root,),
            allow_any=False,
        ),
        strategy=ResourceStrategy(),
    )


async def test_local_resources_are_authorized_and_materialized(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"local-image")
    resources = _resources(tmp_path)
    prepared = prepare_html(
        '<img src="image.png">',
        base_url=f"{tmp_path.as_uri()}/",
    )

    document = await build_htmlkit_document(
        prepared,
        resources=resources,
        resolve_mode=ResourceResolveMode.STRICT,
    )

    assert await document.resources.fetch_image(image.as_uri()) == b"local-image"
    document.resources.raise_callback_error()


async def test_strict_local_access_failure_is_not_hidden(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"forbidden")
    resources = _resources(allowed)
    prepared = prepare_html(
        f'<img src="{outside.as_uri()}">',
        base_url=f"{allowed.as_uri()}/",
    )

    with pytest.raises(ResourceResolutionError, match="outside allowed roots"):
        await build_htmlkit_document(
            prepared,
            resources=resources,
            resolve_mode=ResourceResolveMode.STRICT,
        )


async def test_prepared_assets_work_without_a_second_io_channel(
    tmp_path: Path,
) -> None:
    resources = _resources(tmp_path)
    prepared = prepare_html(
        '<img src="memory:image">',
        assets=(
            PreparedAsset(
                source="memory:image",
                data=b"prepared-image",
                media_type="image/png",
            ),
        ),
    )

    document = await build_htmlkit_document(
        prepared,
        resources=resources,
        resolve_mode=ResourceResolveMode.OFF,
    )

    assert await document.resources.fetch_image("memory:image") == b"prepared-image"


@final
class _FailingRemoteReader:
    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        del reference, refresh
        raise ResourceNotFound("remote asset missing")

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent:
        del revision
        return await self.read(reference)

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        del reference
        return None

    async def invalidate(self, reference: ResourceRef) -> None:
        del reference

    async def clear(self) -> None:
        return None


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        (ResourceResolveMode.AUTO, None),
        (ResourceResolveMode.STRICT, ResourceNotFound),
    ],
)
async def test_callback_failures_follow_resource_strictness(
    tmp_path: Path,
    mode: ResourceResolveMode,
    expected_error: type[ResourceNotFound] | None,
) -> None:
    reader = _FailingRemoteReader()
    resources = ResourceService(
        reader=reader,
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(tmp_path,),
            allow_any=False,
        ),
        strategy=ResourceStrategy(resolve_mode=mode),
    )
    document = await build_htmlkit_document(
        prepare_html('<img src="https://example.test/missing.png">'),
        resources=resources,
        resolve_mode=mode,
    )

    assert (
        await document.resources.fetch_image("https://example.test/missing.png") is None
    )
    if expected_error is not None:
        with pytest.raises(expected_error, match="remote asset missing"):
            document.resources.raise_callback_error()
    else:
        document.resources.raise_callback_error()
