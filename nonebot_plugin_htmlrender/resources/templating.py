"""Shared Jinja template environments with bounded process-local caching."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Any, TypeAlias

from anyio.to_thread import run_sync
import jinja2
from jinja2.ext import Extension

from nonebot_plugin_htmlrender.config import plugin_config

from .source import FilesystemResourceSource, PackageResourceSource

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

FilterCallable: TypeAlias = Callable[..., Any]
ExtensionSpec: TypeAlias = str | type[Extension]
_FilterItem: TypeAlias = tuple[str, FilterCallable]
_IdentityPart: TypeAlias = tuple[str, str | int]
TemplateSource: TypeAlias = (
    str | Path | FilesystemResourceSource | PackageResourceSource
)


@dataclass(frozen=True, slots=True)
class TemplateEnvironmentCacheStats:
    """模板环境缓存的进程级统计快照。"""

    entries: int
    max_entries: int
    hits: int
    misses: int
    evictions: int


@dataclass(frozen=True, slots=True)
class _EnvironmentKey:
    source_identity: tuple[str, ...]
    immutable: bool
    extensions: tuple[_IdentityPart, ...]
    filters: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _EnvironmentEntry:
    environment: jinja2.Environment
    # Jinja 的模板缓存只对单次映射操作加锁。这里覆盖完整的
    # get_template/load 流程，避免并发冷启动时重复读取和编译同一模板。
    template_load_lock: AbstractContextManager[bool] = field(
        default_factory=threading.Lock
    )


@dataclass(slots=True)
class _CacheCounters:
    hits: int = 0
    misses: int = 0
    evictions: int = 0


_DEFAULT_MAX_ENTRIES = 64
_CACHE_LOCK = threading.RLock()
_ENVIRONMENT_CACHE: OrderedDict[_EnvironmentKey, _EnvironmentEntry] = OrderedDict()
_CACHE_COUNTERS = _CacheCounters()


def _get_cache_max_entries() -> int:
    """读取环境缓存上限，并兼容配置字段尚未注册的导入阶段。"""
    configured = getattr(
        plugin_config,
        "render_template_environment_cache_max_entries",
        _DEFAULT_MAX_ENTRIES,
    )
    return max(0, int(configured))


def _normalize_source(
    template_path: TemplateSource,
) -> FilesystemResourceSource | PackageResourceSource:
    if isinstance(template_path, (FilesystemResourceSource, PackageResourceSource)):
        return template_path
    return FilesystemResourceSource(Path(template_path))


def _snapshot_filters(
    filters: Mapping[str, FilterCallable] | None,
) -> tuple[_FilterItem, ...]:
    if not filters:
        return ()

    items: list[_FilterItem] = []
    for name, filter_func in filters.items():
        if not isinstance(name, str):
            raise TypeError("Template filter names must be strings.")
        if not callable(filter_func):
            raise TypeError(f"Template filter {name!r} must be callable.")
        items.append((name, filter_func))
    return tuple(sorted(items, key=lambda item: item[0]))


def _extension_identity(extension: ExtensionSpec) -> _IdentityPart:
    if isinstance(extension, str):
        return ("name", extension)
    return ("type", id(extension))


def _build_key(
    source: FilesystemResourceSource | PackageResourceSource,
    *,
    immutable: bool,
    extensions: tuple[ExtensionSpec, ...],
    filters: tuple[_FilterItem, ...],
) -> _EnvironmentKey:
    return _EnvironmentKey(
        source_identity=tuple(source.identity),
        immutable=immutable,
        extensions=tuple(_extension_identity(extension) for extension in extensions),
        filters=tuple((name, id(filter_func)) for name, filter_func in filters),
    )


def _build_environment(
    source: FilesystemResourceSource | PackageResourceSource,
    *,
    immutable: bool,
    extensions: tuple[ExtensionSpec, ...],
    filters: tuple[_FilterItem, ...],
) -> _EnvironmentEntry:
    if isinstance(source, PackageResourceSource):
        loader: jinja2.BaseLoader = jinja2.PackageLoader(source.package, source.root)
    else:
        loader = jinja2.FileSystemLoader(source.root)
    environment = jinja2.Environment(
        loader=loader,
        extensions=extensions,
        enable_async=True,
        autoescape=jinja2.select_autoescape(),
        auto_reload=not immutable,
    )
    # 在缓存发布前完成过滤器注册。命中缓存时绝不再修改共享环境。
    environment.filters.update(dict(filters))
    return _EnvironmentEntry(environment=environment)


def _enforce_cache_limit_locked(max_entries: int) -> None:
    while len(_ENVIRONMENT_CACHE) > max_entries:
        _ENVIRONMENT_CACHE.popitem(last=False)
        _CACHE_COUNTERS.evictions += 1


def _get_environment_entry(
    source: TemplateSource,
    *,
    immutable: bool,
    extensions: tuple[ExtensionSpec, ...],
    filters: tuple[_FilterItem, ...],
) -> _EnvironmentEntry:
    normalized_source = _normalize_source(source)
    key = _build_key(
        normalized_source,
        immutable=immutable,
        extensions=extensions,
        filters=filters,
    )
    max_entries = _get_cache_max_entries()

    with _CACHE_LOCK:
        _enforce_cache_limit_locked(max_entries)
        cached = _ENVIRONMENT_CACHE.get(key)
        if cached is not None:
            _ENVIRONMENT_CACHE.move_to_end(key)
            _CACHE_COUNTERS.hits += 1
            return cached

        _CACHE_COUNTERS.misses += 1
        entry = _build_environment(
            normalized_source,
            immutable=immutable,
            extensions=extensions,
            filters=filters,
        )
        if max_entries == 0:
            return entry

        _ENVIRONMENT_CACHE[key] = entry
        _enforce_cache_limit_locked(max_entries)
        return entry


def _load_template(
    template_path: TemplateSource,
    template_name: str,
    *,
    immutable: bool,
    extensions: tuple[ExtensionSpec, ...],
    filters: tuple[_FilterItem, ...],
) -> jinja2.Template:
    source = _normalize_source(template_path)
    entry = _get_environment_entry(
        source,
        immutable=immutable,
        extensions=extensions,
        filters=filters,
    )
    with entry.template_load_lock:
        return entry.environment.get_template(template_name)


async def render_template_html(
    template_path: TemplateSource,
    template_name: str,
    variables: Mapping[str, Any],
    *,
    filters: Mapping[str, FilterCallable] | None = None,
    immutable: bool = False,
    extensions: Sequence[ExtensionSpec] = (),
) -> str:
    """使用共享 Jinja 环境异步渲染一个文件系统模板。"""
    filter_snapshot = _snapshot_filters(filters)
    extension_snapshot = tuple(extensions)
    variable_snapshot = dict(variables)

    template = await run_sync(
        partial(
            _load_template,
            template_path,
            template_name,
            immutable=immutable,
            extensions=extension_snapshot,
            filters=filter_snapshot,
        )
    )
    return await template.render_async(**variable_snapshot)


def clear_template_environment_cache() -> None:
    """清空所有模板环境，并重置命中、未命中与驱逐统计。"""
    with _CACHE_LOCK:
        _ENVIRONMENT_CACHE.clear()
        _CACHE_COUNTERS.hits = 0
        _CACHE_COUNTERS.misses = 0
        _CACHE_COUNTERS.evictions = 0


def invalidate_template_environment_cache(template_path: TemplateSource) -> int:
    """移除指定模板根目录对应的全部环境，返回移除数量。"""
    source = _normalize_source(template_path)
    identity = tuple(source.identity)
    with _CACHE_LOCK:
        keys = [key for key in _ENVIRONMENT_CACHE if key.source_identity == identity]
        for key in keys:
            del _ENVIRONMENT_CACHE[key]
        return len(keys)


def get_template_environment_cache_stats() -> TemplateEnvironmentCacheStats:
    """返回模板环境缓存的一致统计快照。"""
    max_entries = _get_cache_max_entries()
    with _CACHE_LOCK:
        return TemplateEnvironmentCacheStats(
            entries=len(_ENVIRONMENT_CACHE),
            max_entries=max_entries,
            hits=_CACHE_COUNTERS.hits,
            misses=_CACHE_COUNTERS.misses,
            evictions=_CACHE_COUNTERS.evictions,
        )


__all__ = [
    "ExtensionSpec",
    "FilterCallable",
    "TemplateEnvironmentCacheStats",
    "TemplateSource",
    "clear_template_environment_cache",
    "get_template_environment_cache_stats",
    "invalidate_template_environment_cache",
    "render_template_html",
]
