"""Resource resolution engine: policy selection, path/URL classification, and single-value resolution."""

from __future__ import annotations

from importlib import import_module
import inspect
from io import BytesIO
from pathlib import Path
import re
from typing import Protocol, TypeGuard
from urllib.parse import urlsplit, urlunsplit

from nonebot.log import logger

from nonebot_plugin_htmlrender.consts import (
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)

from .config import get_resource_config

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


class ResourceResolveError(RuntimeError):
    """Raised when a resource cannot be resolved under strict mode."""


class ResourceResolver(Protocol):
    """资源解析器协议。

    定义将模板中的资源占位符或路径解析为实际可访问 URL/路径的统一接口。
    """

    async def resolve(
        self, value: object, *, template_base: Path | None = None
    ) -> object:
        """将给定值解析为可被渲染端访问的资源引用。

        Args:
            value: 待解析的原始值，通常为字符串或可序列化对象。
            template_base: 模板所在的基准目录，用于解析相对路径。

        Returns:
            解析后可直接供渲染端使用的资源引用。
        """
        ...


async def filehost_url(value: str | Path | bytes, *, lease_id: str | None = None) -> str:
    """Resolve a filehost URL while keeping filehost imports lazy."""
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    resolve_filehost_url = filehost.filehost_url

    return await resolve_filehost_url(value, lease_id=lease_id)


def is_remote_playwright_mode() -> bool:
    """检查当前是否为远程 Playwright 模式。"""
    return get_resource_config().is_remote_mode


def _normalize_template_base(template_base: str | Path | None) -> Path | None:
    """规范化模板基础路径。"""
    if template_base is None:
        return None
    if isinstance(template_base, Path):
        return template_base.expanduser().resolve()
    text = template_base.strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def _is_explicit_url(text: str) -> bool:
    """判断文本是否为显式 URL。"""
    lowered = text.lower()
    return lowered.startswith(
        (
            "http://",
            "https://",
            "file://",
            "data:",
            "about:",
        )
    )


def _is_local_path_string(text: str, template_base: Path | None) -> bool:
    """判断文本是否为本地文件路径。"""
    stripped = text.strip()
    if not stripped:
        return False
    if _is_explicit_url(stripped):
        return False
    if stripped.startswith(("~", "./", "../", "/")):
        return True
    if _WINDOWS_ABS_PATH_RE.match(stripped):
        return True
    if template_base is not None:
        candidate = (template_base / stripped).expanduser()
        if candidate.exists():
            return True
    return ("/" in stripped or "\\" in stripped) and " " not in stripped


def _resolve_local_path(
    value: str | Path,
    *,
    template_base: Path | None = None,
) -> Path:
    """解析本地文件路径为绝对路径。"""
    if isinstance(value, Path):
        path = value.expanduser()
    else:
        path = Path(value.strip()).expanduser()

    if path.is_absolute():
        return path.resolve()
    if template_base is not None:
        return (template_base / path).resolve()
    return path.resolve()


def _is_subpath(path: Path, root: Path) -> bool:
    """判断路径是否为指定根路径的子路径。"""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_filehost_path_allowed(path: Path, *, template_base: Path | None) -> None:
    """验证路径是否在 filehost 允许范围内。"""
    cfg = get_resource_config()
    if cfg.filehost_allow_any_path:
        return

    allowed_roots: list[Path] = []
    if template_base is not None:
        allowed_roots.append(template_base.resolve())
    allowed_roots.extend(
        root.expanduser().resolve() for root in cfg.filehost_allowed_paths
    )

    if not allowed_roots:
        raise ResourceResolveError(
            "Refused to expose local path via filehost without an allowed root. "
            "Provide `template_base`, configure `render_playwright.filehost_allowed_paths`, "
            "or set `render_playwright.filehost_allow_any_path=true` explicitly."
        )

    normalized_path = path.resolve()
    if any(_is_subpath(normalized_path, root) for root in allowed_roots):
        return

    roots = ", ".join(str(root) for root in allowed_roots)
    raise ResourceResolveError(
        f"Local path {normalized_path!s} is outside allowed filehost roots: {roots}."
    )


def _is_bytes_resource(value: object) -> TypeGuard[bytes | bytearray | BytesIO]:
    """判断值是否为字节类型资源。"""
    return isinstance(value, (bytes, bytearray, BytesIO))


def _is_scalar_resource(value: object, template_base: Path | None) -> bool:
    """判断值是否为标量资源（路径、字符串或字节）。"""
    if isinstance(value, Path):
        return True
    if isinstance(value, str):
        return _is_local_path_string(value, template_base)
    return _is_bytes_resource(value)


def _effective_strict(*, strict: bool) -> bool:
    """计算有效的严格模式标志。"""
    if strict:
        return True
    return get_resource_config().resource_resolve_mode == ResourceResolveMode.STRICT


def _pick_policy(resolver: ResourceResolver | str | object | None) -> str:
    """根据解析器选择资源解析策略。"""
    if resolver is None or resolver == "auto":
        cfg = get_resource_config()
        if is_remote_playwright_mode():
            return cfg.remote_local_resource_policy.value
        return cfg.local_local_resource_policy.value
    if resolver == "filehost":
        return "filehost"
    if isinstance(resolver, str):
        raise ValueError(
            "`resource_resolver` must be one of: None, 'auto', 'filehost', or a "
            "custom resolver object."
        )
    if resolver is not None and callable(getattr(resolver, "resolve", None)):
        return "custom"
    if resolver is not None:
        raise ValueError(
            "`resource_resolver` custom object must expose an async `resolve` method."
        )
    return "custom"


def _should_resolve(resolver: ResourceResolver | str | object | None) -> bool:
    """判断是否应执行资源解析。"""
    if resolver is not None and callable(getattr(resolver, "resolve", None)):
        return True
    if resolver == "filehost":
        return True
    if resolver == "auto":
        return True

    return get_resource_config().resource_resolve_mode != ResourceResolveMode.OFF


async def _resolve_scalar_resource(
    value: object,
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | object | None,
    lease_id: str | None = None,
) -> object:
    """解析单个标量资源值。"""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        if _is_explicit_url(stripped):
            return value

    effective_strict = _effective_strict(strict=strict)
    policy = _pick_policy(resolver)

    try:
        if policy == "custom":
            resolve_method = getattr(resolver, "resolve", None)
            if callable(resolve_method):
                resolved_value = resolve_method(value, template_base=template_base)
                if inspect.isawaitable(resolved_value):
                    return await resolved_value
                return resolved_value
            raise ResourceResolveError(
                "`resource_resolver` custom object must expose an async `resolve` method."
            )

        if policy == RemoteLocalResourcePolicy.PASSTHROUGH.value:
            return value

        if policy == RemoteLocalResourcePolicy.ERROR.value:
            raise ResourceResolveError(
                "Local resources are not allowed under current resource policy."
            )

        if policy == "file":
            if isinstance(value, (str, Path)):
                return _resolve_local_path(value, template_base=template_base).as_uri()
            raise ResourceResolveError(
                "`file` resource policy only supports path values."
            )

        if policy == RemoteLocalResourcePolicy.FILEHOST.value:
            if isinstance(value, str):
                value = _resolve_local_path(value, template_base=template_base)
            if isinstance(value, Path):
                value = value.resolve()
                _validate_filehost_path_allowed(value, template_base=template_base)
            if isinstance(value, bytearray):
                value = bytes(value)
            if isinstance(value, BytesIO):
                value = value.getvalue()
            if not isinstance(value, (str, Path, bytes)):
                raise ResourceResolveError(
                    "filehost resource policy only supports path, bytes, or BytesIO values."
                )
            return await filehost_url(value, lease_id=lease_id)

        raise RuntimeError(f"Unsupported resource policy: {policy!r}")
    except Exception as e:
        if effective_strict:
            raise ResourceResolveError(str(e)) from e
        logger.warning(f"Failed to resolve resource {value!r}: {e}")
        return value


def _extract_local_candidate(raw: str) -> tuple[str, str, str] | None:
    """从 URL 字符串中提取本地路径候选。"""
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return None
    return parsed.path, parsed.query, parsed.fragment


def _join_with_original_suffix(
    resolved_value: str,
    *,
    query: str,
    fragment: str,
) -> str:
    """将解析结果与原始查询/片段拼接。"""
    if not query and not fragment:
        return resolved_value
    parsed = urlsplit(resolved_value)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query or parsed.query, fragment)
    )


async def _resolve_url_token(
    raw: str,
    *,
    template_base: Path | None,
    strict: bool,
    resolver: ResourceResolver | str | None,
    lease_id: str | None = None,
) -> str:
    """解析 URL 标记中的本地资源引用。"""
    value = raw.strip()
    if not value:
        return raw
    if value.startswith(("#", "mailto:", "tel:", "javascript:")):
        return raw
    if _is_explicit_url(value):
        return raw

    local_candidate = _extract_local_candidate(value)
    if local_candidate is None:
        return raw
    candidate_path, query, fragment = local_candidate
    if not _is_local_path_string(candidate_path, template_base):
        return raw

    resolved = await _resolve_scalar_resource(
        candidate_path,
        template_base=template_base,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    if not isinstance(resolved, str):
        return raw
    return _join_with_original_suffix(resolved, query=query, fragment=fragment)
