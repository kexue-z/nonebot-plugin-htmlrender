from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.rendering.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources.config import (
    ResourceCacheSettings,
    ResourceResolveMode,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.service import ResourceService

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer


async def test_materialize_recurses_through_stylesheets(
    tmp_path: Path,
    resources: ResourceService,
) -> None:
    styles = tmp_path / "styles"
    styles.mkdir()
    document = tmp_path / "document.html"
    image = tmp_path / "image.png"
    stylesheet = styles / "site.css"
    imported = styles / "theme.css"
    font = styles / "font.woff2"
    image.write_bytes(b"png")
    font.write_bytes(b"font")
    stylesheet.write_text(
        '@import "theme.css"; .hero { background: url(../image.png) }'
    )
    imported.write_text('@font-face { src: url("font.woff2") }')
    prepared = prepare_html(
        '<link rel="stylesheet" href="styles/site.css"><img src="image.png">',
        base_url=document.as_uri(),
    )
    materialized = await materialize_local_assets(prepared, resources=resources)
    assert {asset.source for asset in materialized.assets} == {
        stylesheet.as_uri(),
        imported.as_uri(),
        image.as_uri(),
        font.as_uri(),
    }


async def test_materialize_strict_and_tolerant_modes(
    resources: ResourceService,
) -> None:
    prepared = prepare_html('<img src="relative.png">')
    with pytest.raises(AssetMaterializationError, match="no filesystem base"):
        await materialize_local_assets(prepared, resources=resources)
    assert (
        await materialize_local_assets(prepared, resources=resources, strict=False)
    ).assets == ()


async def test_worker_executor_forwards_keyword_arguments() -> None:
    def work(value: int, *, suffix: str) -> str:
        return f"{value}{suffix}"

    assert await AnyioWorkerExecutor().run_sync(work, 12, suffix="px") == "12px"


async def test_materialize_enforces_document_root(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    prepared = prepare_html(
        f'<base href="{tmp_path.as_uri()}/"><img src="secret.txt">',
        base_url=(allowed / "document.html").as_uri(),
    )
    observer = NoopCacheObserver()
    worker = AnyioWorkerExecutor()
    resources = ResourceService(
        reader=build_resource_reader(
            ResourceCacheSettings(),
            observer,
            worker,
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(
            allowed_roots=(),
            allow_any=False,
        ),
        strategy=ResourceStrategy(),
    )
    with pytest.raises(AssetMaterializationError):
        await materialize_local_assets(prepared, resources=resources)


async def test_markdown_keeps_independent_resource_bases(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
    resources: ResourceService,
) -> None:
    markdown_dir = tmp_path / "markdown"
    css_dir = tmp_path / "theme"
    markdown_dir.mkdir()
    css_dir.mkdir()
    markdown_path = markdown_dir / "document.md"
    image = markdown_dir / "image.png"
    css_path = css_dir / "theme.css"
    font = css_dir / "font.woff2"
    markdown_path.write_text("![image](image.png)")
    image.write_bytes(b"image")
    css_path.write_text('@font-face { src: url("font.woff2") }')
    font.write_bytes(b"font")
    prepared = await preparer.prepare_markdown(
        markdown_path=str(markdown_path),
        css_path=str(css_path),
    )
    materialized = await materialize_local_assets(prepared, resources=resources)
    assert {asset.source for asset in materialized.assets} == {
        image.as_uri(),
        font.as_uri(),
    }


async def test_strict_markdown_preparation_exposes_stable_resource_error(
    preparer: DefaultHtmlPreparer,
) -> None:
    with pytest.raises(ResourceResolutionError, match="no filesystem base") as captured:
        await preparer.prepare_markdown(
            "![missing](missing.png)",
            resource_mode=ResourceResolveMode.STRICT,
        )

    assert isinstance(captured.value, AssetMaterializationError)
