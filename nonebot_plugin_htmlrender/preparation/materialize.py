"""Materialize document-local filesystem references into in-memory assets."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from nonebot.log import logger

from nonebot_plugin_htmlrender.resources import read_resource_bytes
from nonebot_plugin_htmlrender.resources.config import get_resource_config
from nonebot_plugin_htmlrender.resources.path_guard import validate_local_access

from .assets import PreparedAssetIndex, resolve_document_reference
from .models import PreparedAsset, PreparedHtml
from .references import css_resource_references, inspect_html_references


class AssetMaterializationError(RuntimeError):
    """Raised when a local document resource cannot be materialized safely."""


def _file_url_path(url: str) -> Path:
    parsed = urlsplit(url)
    if parsed.scheme != "file":
        raise ValueError(f"Not a file URL: {url!r}")
    if parsed.netloc not in {"", "localhost"}:
        raise AssetMaterializationError(
            f"Remote file URL authorities are not supported: {parsed.netloc!r}"
        )
    return Path(url2pathname(unquote(parsed.path))).expanduser()


def _base_root(base_url: str | None) -> Path | None:
    if not base_url or urlsplit(base_url).scheme != "file":
        return None
    path = _file_url_path(base_url)
    return path if base_url.endswith("/") else path.parent


def _validate_local_path(path: Path, *, base_url: str | None) -> Path:
    cfg = get_resource_config()
    roots: list[Path] = []
    base_root = _base_root(base_url)
    if base_root is not None:
        roots.append(base_root)
    roots.extend(cfg.filehost_allowed_paths)
    normalized_path = validate_local_access(
        path,
        allowed_roots=roots,
        allow_any=cfg.filehost_allow_any_path,
        on_deny=AssetMaterializationError,
    )
    if cfg.filehost_allow_any_path:
        logger.warning(
            f"Reading unrestricted local asset {normalized_path!s} because "
            "filehost_allow_any_path is enabled"
        )
    return normalized_path


async def materialize_local_assets(
    prepared: PreparedHtml,
    *,
    strict: bool = True,
    fallback_base_url: str | None = None,
) -> PreparedHtml:
    """Read referenced file URLs into ``PreparedAsset`` values for this render."""

    assets = list(prepared.assets)
    root_base = prepared.base_url or fallback_base_url
    inspected = inspect_html_references(
        prepared.html,
        base_url=root_base,
    )
    document_base = (
        resolve_document_reference(
            root_base,
            inspected.base_href,
        )
        if inspected.base_href
        else root_base
    )
    index = PreparedAssetIndex(assets, base_url=document_base)
    references: list[tuple[str, str | None, str | None]] = [
        (reference, document_base, root_base) for reference in inspected.references
    ]
    for stylesheet in prepared.stylesheets:
        if stylesheet.embedded:
            continue
        references.extend(
            (
                reference,
                stylesheet.base_url or document_base,
                stylesheet.base_url or root_base,
            )
            for reference in css_resource_references(stylesheet.css)
        )

    pending = deque(references)
    seen_sources = {asset.source for asset in assets}
    expanded_stylesheets: set[str] = set()
    while pending:
        reference, base_url, authorization_base = pending.popleft()
        canonical = resolve_document_reference(base_url, reference)
        existing = index.match(reference, base_url=base_url)
        if existing is not None:
            if (
                existing.media_type == "text/css"
                and canonical not in expanded_stylesheets
            ):
                expanded_stylesheets.add(canonical)
                try:
                    css = existing.data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    logger.warning(
                        f"Could not inspect non-UTF-8 stylesheet asset {reference!r}"
                    )
                else:
                    pending.extend(
                        (child, canonical, authorization_base)
                        for child in css_resource_references(css)
                    )
            continue
        parsed = urlsplit(canonical)
        if parsed.scheme in {"data", "http", "https"} or canonical.startswith("#"):
            continue
        if parsed.scheme != "file":
            message = (
                f"Relative local resource {reference!r} has no filesystem base."
                if not parsed.scheme
                else f"Unsupported local resource scheme for {reference!r}."
            )
            if strict:
                raise AssetMaterializationError(message)
            logger.warning(message)
            continue

        try:
            path = _file_url_path(canonical)
            path = _validate_local_path(path, base_url=authorization_base)
            payload = await read_resource_bytes(path)
        except Exception as error:
            if strict:
                raise AssetMaterializationError(str(error)) from error
            logger.warning(f"Failed to materialize local asset {reference!r}: {error}")
            continue

        if canonical in seen_sources:
            continue
        asset = PreparedAsset(
            source=canonical,
            data=payload,
            media_type=mimetypes.guess_type(path.name)[0],
        )
        assets.append(asset)
        seen_sources.add(canonical)
        index = PreparedAssetIndex(assets, base_url=document_base)
        if asset.media_type == "text/css" and canonical not in expanded_stylesheets:
            expanded_stylesheets.add(canonical)
            try:
                css = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                logger.warning(
                    f"Could not inspect non-UTF-8 stylesheet asset {reference!r}"
                )
            else:
                pending.extend(
                    (child, canonical, authorization_base)
                    for child in css_resource_references(css)
                )

    return replace(prepared, assets=tuple(assets))


__all__ = ["AssetMaterializationError", "materialize_local_assets"]
