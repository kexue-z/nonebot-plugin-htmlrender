from __future__ import annotations

from collections.abc import Mapping, Sequence
from inspect import isawaitable
from io import BytesIO
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, TypeGuard, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

import anyio

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest

from .config import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from .errors import ResourceAccessDenied, ResourceNotFound, ResourceResolutionError
from .models import (
    FileResourceRef,
    InlineResourceRef,
    PackageResourceRef,
    RemoteResourceRef,
    ResourceRef,
)

if TYPE_CHECKING:
    from .config import ResourceStrategy
    from .ports import (
        AssetPublisher,
        LocalAccessPolicy,
        ResourceReader,
        ResourceResolver,
    )

logger = logging.getLogger(__name__)

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_EXPLICIT_POLICIES = frozenset(
    {
        LocalLocalResourcePolicy.FILE.value,
        LocalLocalResourcePolicy.FILEHOST.value,
        LocalLocalResourcePolicy.PASSTHROUGH.value,
        RemoteLocalResourcePolicy.MEMORY.value,
        RemoteLocalResourcePolicy.PASSTHROUGH.value,
        RemoteLocalResourcePolicy.FILEHOST.value,
        RemoteLocalResourcePolicy.ERROR.value,
    }
)


def _resolve_local_path(value: str | Path, *, label: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ResourceResolutionError(
            f"Could not normalize {label}: {error}"
        ) from error


def _normalize_template_base(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    stripped = value if isinstance(value, Path) else value.strip()
    return _resolve_local_path(stripped, label="template base") if stripped else None


def _split_resource_url(value: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as error:
        raise ResourceResolutionError(
            f"Invalid resource URL {value!r}: {error}"
        ) from error


def _is_explicit_url(value: str) -> bool:
    return value.lower().startswith(
        ("http://", "https://", "file://", "data:", "about:")
    )


def _is_bytes(value: object) -> TypeGuard[bytes | bytearray | BytesIO]:
    return isinstance(value, (bytes, bytearray, BytesIO))


def _is_local_string(value: str, template_base: Path | None) -> bool:
    stripped = value.strip()
    if not stripped or _is_explicit_url(stripped):
        return False
    if stripped.startswith(("~", "./", "../", "/")) or _WINDOWS_ABS_PATH_RE.match(
        stripped
    ):
        return True
    if template_base is not None and (template_base / stripped).expanduser().exists():
        return True
    return ("/" in stripped or "\\" in stripped) and " " not in stripped


def _is_scalar(value: object, template_base: Path | None) -> bool:
    return (
        isinstance(value, Path)
        or _is_bytes(value)
        or (isinstance(value, str) and _is_local_string(value, template_base))
    )


def _candidate(value: str | Path, template_base: Path | None) -> Path:
    try:
        path = (
            value.expanduser()
            if isinstance(value, Path)
            else Path(value.strip()).expanduser()
        )
        if not path.is_absolute() and template_base is not None:
            path = template_base / path
        return path.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ResourceResolutionError(
            f"Could not normalize local resource path: {error}"
        ) from error


class ResourceService:
    """Composition-owned resource reading and value-resolution service."""

    def __init__(
        self,
        *,
        reader: ResourceReader,
        local_access: LocalAccessPolicy,
        strategy: ResourceStrategy,
        publisher: AssetPublisher | None = None,
    ) -> None:
        self._reader = reader
        self._local_access = local_access
        self._strategy = strategy
        self._publisher = publisher

    @property
    def strategy(self) -> ResourceStrategy:
        return self._strategy

    def authorize_local(
        self,
        path: Path,
    ) -> Path:
        try:
            return self._local_access.authorize(path)
        except ResourceResolutionError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise ResourceResolutionError(
                f"Could not authorize local resource path: {error}"
            ) from error

    async def read_bytes(
        self,
        reference: str | Path | ResourceRef,
        *,
        refresh: bool = False,
    ) -> bytes:
        normalized = self._reference(reference)
        if isinstance(normalized, FileResourceRef):
            normalized = FileResourceRef(self.authorize_local(normalized.path))
        return (await self._reader.read(normalized, refresh=refresh)).data

    async def read_text(
        self,
        reference: str | Path | ResourceRef,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        refresh: bool = False,
    ) -> str:
        content = await self.read_bytes(
            reference,
            refresh=refresh,
        )
        try:
            return content.decode(encoding, errors)
        except (LookupError, UnicodeError) as error:
            raise ResourceResolutionError(
                f"Could not decode resource as {encoding}: {error}"
            ) from error

    @staticmethod
    def _reference(reference: str | Path | ResourceRef) -> ResourceRef:
        if isinstance(
            reference,
            (
                FileResourceRef,
                PackageResourceRef,
                RemoteResourceRef,
                InlineResourceRef,
            ),
        ):
            return reference
        return FileResourceRef(_resolve_local_path(reference, label="resource path"))

    def _policy(self, resolver: object | None) -> str:
        if resolver is None or resolver == "auto":
            return (
                self._strategy.remote_local_policy.value
                if self._strategy.is_remote
                else self._strategy.local_local_policy.value
            )
        if isinstance(resolver, str):
            if resolver in _EXPLICIT_POLICIES:
                return resolver
            raise InvalidRenderRequest(f"Unknown resource policy: {resolver!r}")
        if callable(getattr(resolver, "resolve", None)):
            return "custom"
        raise InvalidRenderRequest("Custom resource resolver must expose resolve().")

    def should_resolve(self, resolver: object | None = None) -> bool:
        if resolver is not None:
            return True
        return self._strategy.resolve_mode is not ResourceResolveMode.OFF

    async def _resolve_scalar(
        self,
        value: object,
        *,
        template_base: Path | None,
        strict: bool | None,
        resolver: object | None,
        lease_id: str | None,
    ) -> object:
        policy = self._policy(resolver)
        effective_strict = (
            self._strategy.resolve_mode is ResourceResolveMode.STRICT
            if strict is None
            else strict
        )
        try:
            if policy == "custom":
                custom_value = value
                if isinstance(value, (str, Path)):
                    custom_value = self.authorize_local(
                        _candidate(value, template_base),
                    )
                custom_resolver = cast("ResourceResolver", resolver)
                result = custom_resolver.resolve(
                    custom_value,
                    template_base=template_base,
                )
                return await result if isawaitable(result) else result
            if policy in {"passthrough", "memory"}:
                return value
            if policy == "error":
                raise ResourceResolutionError(
                    "Local resources are disabled by the resource strategy."
                )
            if policy == "file":
                if not isinstance(value, (str, Path)):
                    raise ResourceResolutionError(
                        "The file policy only accepts path values."
                    )
                path = self.authorize_local(
                    _candidate(value, template_base),
                )
                return path.as_uri()
            if policy == "filehost":
                if self._publisher is None:
                    raise ResourceResolutionError(
                        "The filehost policy requires an AssetPublisher."
                    )
                publish_value: str | Path | bytes
                if isinstance(value, str):
                    value = _candidate(value, template_base)
                if isinstance(value, Path):
                    publish_value = self.authorize_local(value)
                elif isinstance(value, BytesIO):
                    publish_value = value.getvalue()
                elif isinstance(value, bytearray):
                    publish_value = bytes(value)
                elif isinstance(value, bytes):
                    publish_value = value
                else:
                    raise ResourceResolutionError(
                        "The filehost policy only accepts paths or bytes."
                    )
                return await self._publisher.publish(publish_value, lease_id=lease_id)
            raise ResourceResolutionError(f"Unsupported resource policy: {policy!r}")
        except Exception as error:
            if policy == "error" or effective_strict:
                if isinstance(error, ResourceResolutionError):
                    raise
                if isinstance(error, FileNotFoundError):
                    raise ResourceNotFound(str(error)) from error
                if isinstance(error, PermissionError):
                    raise ResourceAccessDenied(str(error)) from error
                raise ResourceResolutionError(str(error)) from error
            logger.warning("Failed to resolve resource %r: %s", value, error)
            return value

    async def _resolve_any(
        self,
        value: object,
        *,
        template_base: Path | None,
        strict: bool | None,
        resolver: object | None,
        lease_id: str | None,
    ) -> object:
        if _is_scalar(value, template_base):
            return await self._resolve_scalar(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        if isinstance(value, Mapping):
            items = tuple(value.items())
            resolved = await self._resolve_many(
                tuple(item[1] for item in items),
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
            return {key: item for (key, _), item in zip(items, resolved, strict=True)}
        if isinstance(value, tuple):
            return tuple(
                await self._resolve_many(
                    value,
                    template_base=template_base,
                    strict=strict,
                    resolver=resolver,
                    lease_id=lease_id,
                )
            )
        if isinstance(value, list):
            return await self._resolve_many(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        if isinstance(value, set):
            resolved = await self._resolve_many(
                tuple(value),
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
            try:
                return set(resolved)
            except TypeError as error:
                raise ResourceResolutionError(
                    "Resolved set items must remain hashable."
                ) from error
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return await self._resolve_many(
                value,
                template_base=template_base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
        return value

    async def _resolve_many(
        self,
        values: Sequence[object],
        *,
        template_base: Path | None,
        strict: bool | None,
        resolver: object | None,
        lease_id: str | None,
    ) -> list[object]:
        results: list[object] = [None] * len(values)
        errors: list[Exception | None] = [None] * len(values)

        async def resolve_one(index: int, value: object) -> None:
            try:
                results[index] = await self._resolve_any(
                    value,
                    template_base=template_base,
                    strict=strict,
                    resolver=resolver,
                    lease_id=lease_id,
                )
            except Exception as error:
                errors[index] = error

        async with anyio.create_task_group() as group:
            for index, value in enumerate(values):
                group.start_soon(resolve_one, index, value)
        if error := next((error for error in errors if error is not None), None):
            raise error
        return results

    async def resolve_template_vars(
        self,
        template_vars: Mapping[str, Any],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: object | None = None,
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.should_resolve(resolver):
            return dict(template_vars)
        result = await self._resolve_any(
            template_vars,
            template_base=_normalize_template_base(template_base),
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )
        if not isinstance(result, dict):
            raise ResourceResolutionError(
                "Resolved template variables must remain a mapping."
            )
        return cast("dict[str, Any]", result)

    async def to_resource_url(
        self,
        value: str | Path | bytes,
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: object | None = None,
        lease_id: str | None = None,
    ) -> str:
        result = await self._resolve_any(
            value,
            template_base=_normalize_template_base(template_base),
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
        )
        if not isinstance(result, str):
            raise ResourceResolutionError(
                f"Resolved resource is not URL text: {type(result).__name__}."
            )
        return result

    async def resolve_url_tokens(
        self,
        values: Sequence[str],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: object | None = None,
        lease_id: str | None = None,
    ) -> list[str]:
        base = _normalize_template_base(template_base)
        resolved: list[str] = []
        for raw in values:
            parsed = _split_resource_url(raw)
            if parsed.scheme or parsed.netloc or raw.startswith(("data:", "#")):
                resolved.append(raw)
                continue
            value = await self._resolve_scalar(
                parsed.path,
                template_base=base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
            )
            if not isinstance(value, str):
                resolved.append(raw)
                continue
            target = _split_resource_url(value)
            resolved.append(
                urlunsplit(
                    (
                        target.scheme,
                        target.netloc,
                        target.path,
                        parsed.query or target.query,
                        parsed.fragment,
                    )
                )
            )
        return resolved

    async def clear(self) -> None:
        await self._reader.clear()


__all__ = ["ResourceService"]
