from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._default import get_default_application

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from nonebot_plugin_htmlrender.resources.models import ResourceResolution
    from nonebot_plugin_htmlrender.resources.service import ResolverSpec


async def resolve_template_vars(
    template_vars: Mapping[str, Any],
    *,
    template_base: str | Path | None = None,
    strict: bool | None = None,
    resolver: ResolverSpec = None,
) -> ResourceResolution[dict[str, Any]]:
    return await get_default_application().resources.resolve_template_vars(
        template_vars,
        template_base=template_base,
        strict=strict,
        resolver=resolver,
    )


async def to_resource_url(
    value: str | Path | bytes,
    *,
    template_base: str | Path | None = None,
    strict: bool | None = None,
    resolver: ResolverSpec = None,
) -> ResourceResolution[str]:
    return await get_default_application().resources.to_resource_url(
        value,
        template_base=template_base,
        strict=strict,
        resolver=resolver,
    )


__all__ = ["resolve_template_vars", "to_resource_url"]
