from __future__ import annotations

from inspect import isawaitable
from io import BytesIO
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, TypeAlias, TypeGuard
from urllib.parse import SplitResult, urlsplit, urlunsplit

import anyio
from nonebot.log import logger

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest

from ._traversal import ResourceTraversalBudget, VariableResolutionPlan
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
    PublishedResource,
    RemoteResourceRef,
    ResourceRef,
    ResourceResolution,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .config import ResourceStrategy
    from .ports import (
        AssetPublisher,
        LocalAccessPolicy,
        ResourceReader,
        ResourceResolver,
    )

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")

TransportPolicy: TypeAlias = "LocalLocalResourcePolicy | RemoteLocalResourcePolicy"
ResolverSpec: TypeAlias = "str | ResourceResolver | None"
RequestHeadersByUrl: TypeAlias = "dict[str, Mapping[str, str]]"

# Derived from the enum members themselves so a value rename cannot leave a
# stale string behind.  Members whose values overlap across the two enums
# (passthrough/filehost) share identical semantics in ``_resolve_scalar``.
_EXPLICIT_POLICIES: Mapping[str, TransportPolicy] = {
    member.value: member
    for enum_cls in (RemoteLocalResourcePolicy, LocalLocalResourcePolicy)
    for member in enum_cls
}


def _is_string_keyed_dict(value: dict[Any, Any]) -> TypeGuard[dict[str, Any]]:
    return all(isinstance(key, str) for key in value)


def _resolve_local_path(value: str | Path, *, label: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ResourceResolutionError(
            f"Could not normalize {label}.",
            source=error,
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
            f"Invalid resource URL {value!r}.",
            source=error,
        ) from error


def _is_explicit_url(value: str) -> bool:
    return value.lower().startswith(
        ("http://", "https://", "file://", "data:", "about:")
    )


def _is_bytes(value: object) -> TypeGuard[bytes | bytearray | BytesIO]:
    return isinstance(value, (bytes, bytearray, BytesIO))


def _is_local_string(value: str) -> bool:
    """Classify by string shape only.

    Classification must stay free of filesystem probes: touching the
    filesystem here would let arbitrary template text trigger reads and leak
    existence information before any policy check runs.  Bare names without a
    path shape stay text; callers express path intent with ``Path`` values,
    explicit ``./``-style prefixes, or concrete ``ResourceRef`` objects.
    """
    stripped = value.strip()
    if not stripped or _is_explicit_url(stripped):
        return False
    if stripped.startswith(("~", "./", "../", "/")) or _WINDOWS_ABS_PATH_RE.match(
        stripped
    ):
        return True
    return ("/" in stripped or "\\" in stripped) and " " not in stripped


def _is_scalar(value: object) -> bool:
    return (
        isinstance(value, Path)
        or _is_bytes(value)
        or (isinstance(value, str) and _is_local_string(value))
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
            "Could not normalize local resource path.",
            source=error,
        ) from error


class _ConflictingRequestAuthorization(ResourceResolutionError):
    """A publisher reused one URL with incompatible request capabilities."""


def _record_published_resource(
    published: PublishedResource,
    request_headers_by_url: RequestHeadersByUrl,
) -> None:
    headers = dict(published.request_headers)
    existing = request_headers_by_url.get(published.url)
    if existing is not None and dict(existing) != headers:
        raise _ConflictingRequestAuthorization(
            "The asset publisher returned conflicting authorization for one URL."
        )
    request_headers_by_url[published.url] = headers


class ResourceService:
    """Composition-owned resource reading and value-resolution service."""

    def __init__(
        self,
        *,
        reader: ResourceReader,
        local_access: LocalAccessPolicy,
        strategy: ResourceStrategy,
        publisher: AssetPublisher | None = None,
        traversal_budget: ResourceTraversalBudget | None = None,
    ) -> None:
        budget = traversal_budget or ResourceTraversalBudget()
        self._reader = reader
        self._local_access = local_access
        self._strategy = strategy
        self._publisher = publisher
        self._traversal_budget = budget
        self._scalar_slots = anyio.Semaphore(budget.max_concurrency)

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
                "Could not authorize a local resource path.",
                source=error,
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
                f"Could not decode resource as {encoding}.",
                source=error,
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

    def _policy(self, resolver: ResolverSpec) -> TransportPolicy | ResourceResolver:
        if resolver is None or resolver == "auto":
            return (
                self._strategy.remote_local_policy
                if self._strategy.is_remote
                else self._strategy.local_local_policy
            )
        if isinstance(resolver, str):
            member = _EXPLICIT_POLICIES.get(resolver)
            if member is None:
                raise InvalidRenderRequest(f"Unknown resource policy: {resolver!r}")
            return member
        if callable(getattr(resolver, "resolve", None)):
            return resolver
        raise InvalidRenderRequest("Custom resource resolver must expose resolve().")

    def should_resolve(self, resolver: ResolverSpec = None) -> bool:
        if resolver is not None:
            return True
        return self._strategy.resolve_mode is not ResourceResolveMode.OFF

    async def _resolve_with_custom(
        self,
        resolver: ResourceResolver,
        value: object,
        *,
        template_base: Path | None,
    ) -> object:
        custom_value = value
        if isinstance(value, (str, Path)):
            custom_value = self.authorize_local(_candidate(value, template_base))
        result = resolver.resolve(custom_value, template_base=template_base)
        return await result if isawaitable(result) else result

    async def _resolve_with_policy(
        self,
        policy: TransportPolicy,
        value: object,
        *,
        template_base: Path | None,
        lease_id: str | None,
        request_headers_by_url: RequestHeadersByUrl,
    ) -> object:
        if policy in (
            LocalLocalResourcePolicy.PASSTHROUGH,
            RemoteLocalResourcePolicy.MEMORY,
        ):
            return value
        if policy is RemoteLocalResourcePolicy.ERROR:
            raise ResourceResolutionError(
                "Local resources are disabled by the resource strategy."
            )
        if policy is LocalLocalResourcePolicy.FILE:
            if not isinstance(value, (str, Path)):
                raise ResourceResolutionError(
                    "The file policy only accepts path values."
                )
            return self.authorize_local(_candidate(value, template_base)).as_uri()
        if policy in (
            LocalLocalResourcePolicy.FILEHOST,
            RemoteLocalResourcePolicy.FILEHOST,
        ):
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
            published = await self._publisher.publish(publish_value, lease_id=lease_id)
            _record_published_resource(published, request_headers_by_url)
            return published.url
        raise ResourceResolutionError(f"Unsupported resource policy: {policy!r}")

    async def _resolve_scalar(
        self,
        value: object,
        *,
        template_base: Path | None,
        strict: bool | None,
        resolver: ResolverSpec,
        lease_id: str | None,
        request_headers_by_url: RequestHeadersByUrl,
    ) -> object:
        policy = self._policy(resolver)
        effective_strict = (
            self._strategy.resolve_mode is ResourceResolveMode.STRICT
            if strict is None
            else strict
        )
        try:
            async with self._scalar_slots:
                if isinstance(
                    policy, (LocalLocalResourcePolicy, RemoteLocalResourcePolicy)
                ):
                    return await self._resolve_with_policy(
                        policy,
                        value,
                        template_base=template_base,
                        lease_id=lease_id,
                        request_headers_by_url=request_headers_by_url,
                    )
                return await self._resolve_with_custom(
                    policy,
                    value,
                    template_base=template_base,
                )
        except Exception as error:
            if isinstance(error, _ConflictingRequestAuthorization):
                raise
            if policy is RemoteLocalResourcePolicy.ERROR or effective_strict:
                if isinstance(error, ResourceResolutionError):
                    raise
                if isinstance(error, FileNotFoundError):
                    raise ResourceNotFound(
                        "Resource was not found.", source=error
                    ) from error
                if isinstance(error, PermissionError):
                    raise ResourceAccessDenied(
                        "Resource access was denied.", source=error
                    ) from error
                raise ResourceResolutionError(
                    "Resource resolution failed.", source=error
                ) from error
            logger.warning(
                "Failed to resolve a resource (non-strict policy): {}",
                type(error).__name__,
            )
            return value

    async def _resolve_any(
        self,
        value: object,
        *,
        template_base: Path | None,
        strict: bool | None,
        resolver: ResolverSpec,
        lease_id: str | None,
        request_headers_by_url: RequestHeadersByUrl,
    ) -> object:
        plan = VariableResolutionPlan.build(
            value,
            budget=self._traversal_budget,
        )
        jobs = tuple(leaf for leaf in plan.leaves if _is_scalar(leaf.value))
        if not jobs:
            return plan.rebuild({})

        resolved: dict[int, object] = {}
        errors: dict[int, Exception] = {}
        failed = anyio.Event()
        cursor = 0
        cursor_lock = anyio.Lock()

        async def take_job() -> tuple[int, object] | None:
            nonlocal cursor
            async with cursor_lock:
                if failed.is_set() or cursor >= len(jobs):
                    return None
                leaf = jobs[cursor]
                cursor += 1
                return leaf.node_index, leaf.value

        async def worker() -> None:
            while (job := await take_job()) is not None:
                node_index, leaf_value = job
                try:
                    resolved[node_index] = await self._resolve_scalar(
                        leaf_value,
                        template_base=template_base,
                        strict=strict,
                        resolver=resolver,
                        lease_id=lease_id,
                        request_headers_by_url=request_headers_by_url,
                    )
                except Exception as error:
                    errors[node_index] = error
                    failed.set()

        worker_count = min(self._traversal_budget.max_concurrency, len(jobs))
        async with anyio.create_task_group() as group:
            for _ in range(worker_count):
                group.start_soon(worker)

        if errors:
            for leaf in jobs:
                if error := errors.get(leaf.node_index):
                    raise error
            raise RuntimeError("Variable resolution failed without a recorded error.")

        return plan.rebuild(resolved)

    async def resolve_template_vars(
        self,
        template_vars: Mapping[str, Any],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[dict[str, Any]]:
        request_headers_by_url: RequestHeadersByUrl = {}
        if not self.should_resolve(resolver):
            return ResourceResolution(dict(template_vars))
        result = await self._resolve_any(
            template_vars,
            template_base=_normalize_template_base(template_base),
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
            request_headers_by_url=request_headers_by_url,
        )
        if not isinstance(result, dict):
            raise ResourceResolutionError(
                "Resolved template variables must remain a mapping."
            )
        if not _is_string_keyed_dict(result):
            raise ResourceResolutionError(
                "Resolved template variable keys must remain strings."
            )
        return ResourceResolution(
            result,
            request_headers_by_url,
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
        request_headers_by_url: RequestHeadersByUrl = {}
        result = await self._resolve_any(
            value,
            template_base=_normalize_template_base(template_base),
            strict=strict,
            resolver=resolver,
            lease_id=lease_id,
            request_headers_by_url=request_headers_by_url,
        )
        if not isinstance(result, str):
            raise ResourceResolutionError(
                f"Resolved resource is not URL text: {type(result).__name__}."
            )
        return ResourceResolution(result, request_headers_by_url)

    async def resolve_url_tokens(
        self,
        values: Sequence[str],
        *,
        template_base: str | Path | None = None,
        strict: bool | None = None,
        resolver: ResolverSpec = None,
        lease_id: str | None = None,
    ) -> ResourceResolution[list[str]]:
        base = _normalize_template_base(template_base)
        resolved: list[str] = []
        request_headers_by_url: RequestHeadersByUrl = {}
        for raw in values:
            parsed = _split_resource_url(raw)
            if parsed.scheme or parsed.netloc or raw.startswith(("data:", "#")):
                resolved.append(raw)
                continue
            token_headers_by_url: RequestHeadersByUrl = {}
            value = await self._resolve_scalar(
                parsed.path,
                template_base=base,
                strict=strict,
                resolver=resolver,
                lease_id=lease_id,
                request_headers_by_url=token_headers_by_url,
            )
            if not isinstance(value, str):
                resolved.append(raw)
                continue
            target = _split_resource_url(value)
            resolved_url = urlunsplit(
                (
                    target.scheme,
                    target.netloc,
                    target.path,
                    parsed.query or target.query,
                    parsed.fragment,
                )
            )
            resolved.append(resolved_url)
            headers = token_headers_by_url.get(value)
            if headers is not None:
                _record_published_resource(
                    PublishedResource(resolved_url, headers),
                    request_headers_by_url,
                )
        return ResourceResolution(resolved, request_headers_by_url)

    async def clear(self) -> None:
        await self._reader.clear()


__all__ = ["ResolverSpec", "ResourceService", "TransportPolicy"]
