"""Template variable resolution, HTML attribute rewriting, and CSS url() rewriting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import unescape
from typing import TYPE_CHECKING, Any, cast

import anyio

from .resolve import (
    ResourceResolveError,
    ResourceResolver,
    _is_scalar_resource,
    _normalize_template_base,
    _resolve_scalar_resource,
    _resolve_url_token,
    _should_resolve,
)

if TYPE_CHECKING:
    from pathlib import Path


async def _resolve_many(
    values: Sequence[object],
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None,
) -> list[object]:
    """并发解析多个资源值。"""
    resolved: list[object] = [None] * len(values)
    first_error: Exception | None = None
    error_lock = anyio.Lock()

    async def _resolve_one(index: int, nested_value: object) -> None:
        nonlocal first_error
        try:
            resolved[index] = await _resolve_any(
                nested_value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        except Exception as e:
            async with error_lock:
                if first_error is None:
                    first_error = e

    async with anyio.create_task_group() as tg:
        for index, nested_value in enumerate(values):
            tg.start_soon(_resolve_one, index, nested_value)

    if first_error is not None:
        raise first_error
    return resolved


async def _resolve_url_tokens_many(
    values: Sequence[str],
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None,
) -> list[str]:
    """并发解析多个 URL 标记。"""
    resolved = [""] * len(values)
    first_error: Exception | None = None
    error_lock = anyio.Lock()

    async def _resolve_one(index: int, value: str) -> None:
        nonlocal first_error
        try:
            resolved[index] = await _resolve_url_token(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        except Exception as e:
            async with error_lock:
                if first_error is None:
                    first_error = e

    async with anyio.create_task_group() as tg:
        for index, value in enumerate(values):
            tg.start_soon(_resolve_one, index, value)

    if first_error is not None:
        raise first_error
    return resolved


async def _resolve_any(
    value: object,
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None = None,
) -> object:
    """递归解析任意类型的资源值。"""
    if _is_scalar_resource(value, template_base):
        return await _resolve_scalar_resource(
            value,
            template_base=template_base,
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )

    if isinstance(value, Mapping):
        items = tuple(value.items())
        resolved_values = await _resolve_many(
            [nested_value for _, nested_value in items],
            template_base=template_base,
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )
        return {
            key: resolved_value
            for (key, _), resolved_value in zip(items, resolved_values, strict=True)
        }

    if isinstance(value, tuple):
        return tuple(
            await _resolve_many(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        )

    if isinstance(value, list):
        return await _resolve_many(
            value,
            template_base=template_base,
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )

    if isinstance(value, set):
        return set(
            await _resolve_many(
                tuple(value),
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        )

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return await _resolve_many(
            value,
            template_base=template_base,
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )

    return value


async def _resolve_html_attr_resources(
    html: str,
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None = None,
) -> str:
    """Resolve real HTML/CSS resource tokens without scanning comments/scripts."""

    from nonebot_plugin_htmlrender.preparation.references import (  # noqa: PLC0415
        inspect_html_references,
        rewrite_html_references,
    )

    references = tuple(dict.fromkeys(inspect_html_references(html).references))
    resolved_values = await _resolve_url_tokens_many(
        references,
        template_base=template_base,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    replacements = dict(zip(references, resolved_values, strict=True))

    def rewrite(reference: str) -> str | None:
        replacement = replacements.get(reference)
        if replacement is not None:
            return replacement
        return replacements.get(unescape(reference))

    return rewrite_html_references(html, rewrite)


async def _resolve_css_url_resources(
    html: str,
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None = None,
) -> str:
    """Compatibility stage; CSS tokens are resolved with their owning HTML token."""

    del template_base, strict, resolver, lease_id
    return html


async def resolve_template_vars(
    template_vars: dict[str, Any],
    *,
    template_base: str | Path | None = None,
    strict: bool = False,
    resolver: ResourceResolver | str | None = None,
    lease_id: str | None = None,
) -> dict[str, Any]:
    """解析模板变量中的资源引用。"""
    if not _should_resolve(resolver):
        return dict(template_vars)

    base_path = _normalize_template_base(template_base)
    resolved = await _resolve_any(
        template_vars,
        template_base=base_path,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    if not isinstance(resolved, dict):
        raise ResourceResolveError("Resolved template vars must remain a dictionary.")
    return cast("dict[str, Any]", resolved)


async def resolve_html_resources(
    html: str,
    *,
    template_base: str | Path | None = None,
    strict: bool = False,
    resolver: ResourceResolver | str | None = None,
    lease_id: str | None = None,
) -> str:
    """解析 HTML 内容中的所有资源引用。"""
    if not _should_resolve(resolver):
        return html

    base_path = _normalize_template_base(template_base)
    rewritten = await _resolve_html_attr_resources(
        html,
        template_base=base_path,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    return await _resolve_css_url_resources(
        rewritten,
        template_base=base_path,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )


async def to_resource_url(
    value: str | Path | bytes,
    *,
    template_base: str | Path | None = None,
    strict: bool = False,
    resolver: ResourceResolver | str | None = None,
    lease_id: str | None = None,
) -> str:
    """将资源值转换为 URL 字符串。"""
    resolved = await _resolve_any(
        value,
        template_base=_normalize_template_base(template_base),
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    if not isinstance(resolved, str):
        raise ResourceResolveError(
            f"Resolved resource is not URL text: got {type(resolved).__name__}."
        )
    return resolved
