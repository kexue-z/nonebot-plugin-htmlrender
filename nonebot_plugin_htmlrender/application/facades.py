"""Lifecycle-bound facades for services exposed by :class:`Application`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
    from nonebot_plugin_htmlrender.resources.config import (
        ResourceResolveMode,
        ResourceStrategy,
    )
    from nonebot_plugin_htmlrender.resources.models import (
        ResourceRef,
        ResourceResolution,
    )
    from nonebot_plugin_htmlrender.resources.service import (
        ResolverSpec,
        ResourceService,
    )
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )


class ApplicationResources(Protocol):
    """Resource operations exposed through an application's lifetime."""

    @property
    def strategy(self) -> ResourceStrategy: ...

    def authorize_local(self, path: Path) -> Path: ...

    async def read_bytes(
        self,
        reference: str | Path | ResourceRef,
        *,
        refresh: bool = False,
    ) -> bytes: ...

    async def read_text(
        self,
        reference: str | Path | ResourceRef,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        refresh: bool = False,
    ) -> str: ...

    def should_resolve(self, resolver: ResolverSpec = None) -> bool: ...

    async def resolve_template_vars(
        self,
        template_vars: Mapping[str, Any],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[dict[str, Any]]: ...

    async def to_resource_url(
        self,
        value: str | Path | bytes,
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[str]: ...

    async def resolve_url_tokens(
        self,
        values: Sequence[str],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[list[str]]: ...

    async def clear(self) -> None: ...


@final
class AdmittedHtmlPreparer:
    """Keep retained public preparation references inside admission control."""

    def __init__(
        self,
        delegate: HtmlPreparer,
        admission: OperationAdmissionGate,
    ) -> None:
        self._delegate = delegate
        self._admission = admission

    async def prepare_html(
        self,
        html: str,
        *,
        base_url: str | None = None,
    ) -> PreparedHtml:
        async with self._admission.operation():
            return await self._delegate.prepare_html(html, base_url=base_url)

    async def prepare_text(
        self,
        text: str,
        *,
        css_path: str = "",
    ) -> PreparedHtml:
        async with self._admission.operation():
            return await self._delegate.prepare_text(text, css_path=css_path)

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml:
        async with self._admission.operation():
            return await self._delegate.prepare_markdown(
                markdown_text,
                markdown_path=markdown_path,
                css_path=css_path,
                resource_mode=resource_mode,
            )

    async def prepare_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml:
        async with self._admission.operation():
            return await self._delegate.prepare_template(
                template_path,
                template_name,
                variables,
                filters=filters,
                extensions=extensions,
                resource_mode=resource_mode,
            )

    async def render_template_html(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str:
        async with self._admission.operation():
            return await self._delegate.render_template_html(
                template_path,
                template_name,
                variables,
                filters=filters,
                extensions=extensions,
            )


@final
class AdmittedResourceService:
    """Keep public resource access from outliving its application caches."""

    def __init__(
        self,
        delegate: ResourceService,
        admission: OperationAdmissionGate,
    ) -> None:
        self._delegate = delegate
        self._admission = admission

    @property
    def strategy(self) -> ResourceStrategy:
        return self._delegate.strategy

    def authorize_local(self, path: Path) -> Path:
        self._admission.ensure_accepting()
        return self._delegate.authorize_local(path)

    async def read_bytes(
        self,
        reference: str | Path | ResourceRef,
        *,
        refresh: bool = False,
    ) -> bytes:
        async with self._admission.operation():
            return await self._delegate.read_bytes(reference, refresh=refresh)

    async def read_text(
        self,
        reference: str | Path | ResourceRef,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        refresh: bool = False,
    ) -> str:
        async with self._admission.operation():
            return await self._delegate.read_text(
                reference,
                encoding=encoding,
                errors=errors,
                refresh=refresh,
            )

    def should_resolve(self, resolver: ResolverSpec = None) -> bool:
        self._admission.ensure_accepting()
        return self._delegate.should_resolve(resolver)

    async def resolve_template_vars(
        self,
        template_vars: Mapping[str, Any],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[dict[str, Any]]:
        async with self._admission.operation():
            return await self._delegate.resolve_template_vars(
                template_vars,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )

    async def to_resource_url(
        self,
        value: str | Path | bytes,
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[str]:
        async with self._admission.operation():
            return await self._delegate.to_resource_url(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )

    async def resolve_url_tokens(
        self,
        values: Sequence[str],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[list[str]]:
        async with self._admission.operation():
            return await self._delegate.resolve_url_tokens(
                values,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )

    async def clear(self) -> None:
        async with self._admission.operation():
            await self._delegate.clear()


__all__ = [
    "AdmittedHtmlPreparer",
    "AdmittedResourceService",
    "ApplicationResources",
]
