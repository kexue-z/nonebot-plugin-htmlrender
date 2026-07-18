from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation.html import prepare_html as prepare_html
from nonebot_plugin_htmlrender.rendering.requests import (
    ResourcePolicy,
    resolve_mode_for_policy,
)

from ._default import get_default_application

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )


async def prepare_text(text: str, *, css_path: str = "") -> PreparedHtml:
    return await get_default_application().preparation.prepare_text(
        text, css_path=css_path
    )


async def prepare_markdown(
    markdown: str = "",
    *,
    markdown_path: str = "",
    css_path: str = "",
    resource_policy: ResourcePolicy | None = None,
) -> PreparedHtml:
    resource_mode = (
        None if resource_policy is None else resolve_mode_for_policy(resource_policy)
    )
    return await get_default_application().preparation.prepare_markdown(
        markdown,
        markdown_path=markdown_path,
        css_path=css_path,
        resource_mode=resource_mode,
    )


async def prepare_template(
    template_path: str | Path,
    template_name: str,
    variables: Mapping[str, object],
    *,
    filters: Mapping[str, FilterCallable] | None = None,
    extensions: Sequence[ExtensionSpec] = (),
) -> PreparedHtml:
    return await get_default_application().preparation.prepare_template(
        template_path,
        template_name,
        variables,
        filters=filters,
        extensions=extensions,
    )


__all__ = ["prepare_html", "prepare_markdown", "prepare_template", "prepare_text"]
