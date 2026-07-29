"""Stage binary template variables into backend-neutral prepared assets."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio

from .media import sniff_media_type
from .models import PreparedAsset

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot_plugin_htmlrender.resources.service import ResourceService


class _PreparedAssetResolver:
    def __init__(self) -> None:
        self._assets: dict[str, PreparedAsset] = {}
        self._lock = anyio.Lock()

    async def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> object:
        if isinstance(value, Path):
            path = value.expanduser()
            if not path.is_absolute() and template_base is not None:
                path = template_base / path
            return path.resolve().as_uri()
        if isinstance(value, BytesIO):
            payload = value.getvalue()
        elif isinstance(value, bytearray):
            payload = bytes(value)
        elif isinstance(value, bytes):
            payload = value
        else:
            return value

        digest = sha256(payload).hexdigest()
        source = f"memory://htmlrender/template-assets/{digest}"
        asset = PreparedAsset(
            source=source,
            data=payload,
            media_type=sniff_media_type(payload),
        )
        async with self._lock:
            self._assets.setdefault(source, asset)
        return source

    def assets(self) -> tuple[PreparedAsset, ...]:
        return tuple(self._assets[source] for source in sorted(self._assets))


async def stage_template_variables(
    variables: Mapping[str, Any],
    *,
    template_base: str | Path,
    resources: ResourceService,
    strict: bool,
) -> tuple[dict[str, Any], tuple[PreparedAsset, ...]]:
    """Replace Path/binary variables with stable URL identifiers and assets."""

    resolver = _PreparedAssetResolver()
    resolved = await resources.resolve_template_vars(
        dict(variables),
        template_base=template_base,
        strict=strict,
        resolver=resolver,
    )
    return resolved.value, resolver.assets()


__all__ = ["stage_template_variables"]
