from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Any

import jinja2

from nonebot_plugin_htmlrender.errors import PreparationError, RenderingError
from nonebot_plugin_htmlrender.resources.source import (
    FilesystemResourceSource,
    PackageResourceSource,
)
from nonebot_plugin_htmlrender.resources.templating import (
    ExtensionSpec,
    FilterCallable,
    TemplateEnvironmentCacheStats,
    TemplateSource,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractContextManager

    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import (
        LocalAccessPolicy,
        WorkerExecutor,
    )


@dataclass(frozen=True, slots=True)
class _Identity:
    value: object

    def __hash__(self) -> int:
        return id(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Identity) and self.value is other.value


@dataclass(frozen=True, slots=True)
class _Key:
    source: tuple[str, ...]
    immutable: bool
    extensions: tuple[tuple[str, str | _Identity], ...]
    filters: tuple[tuple[str, _Identity], ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    environment: jinja2.Environment
    load_lock: AbstractContextManager[bool] = field(default_factory=threading.Lock)


class JinjaTemplateCompiler:
    """Instance-scoped Jinja compiler with an injected bounded cache."""

    def __init__(
        self,
        *,
        max_entries: int,
        observer: CacheObserver,
        worker: WorkerExecutor,
        local_access: LocalAccessPolicy,
        cache_size: int = 256,
    ) -> None:
        if max_entries < 0:
            raise ValueError("Template cache size must not be negative")
        if cache_size < 0:
            raise ValueError("Compiled-template cache size must not be negative")
        self._max_entries = max_entries
        self._cache_size = cache_size
        self._observer = observer
        self._worker = worker
        self._local_access = local_access
        self._entries: OrderedDict[_Key, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _source(
        self,
        value: TemplateSource,
    ) -> FilesystemResourceSource | PackageResourceSource:
        if isinstance(value, PackageResourceSource):
            return value
        root = (
            value.root if isinstance(value, FilesystemResourceSource) else Path(value)
        )
        return FilesystemResourceSource(self._local_access.authorize(root))

    @staticmethod
    def _extensions(
        values: Sequence[ExtensionSpec],
    ) -> tuple[tuple[str, str | _Identity], ...]:
        return tuple(
            ("name", value) if isinstance(value, str) else ("type", _Identity(value))
            for value in values
        )

    def _key(
        self,
        source: FilesystemResourceSource | PackageResourceSource,
        *,
        immutable: bool,
        extensions: Sequence[ExtensionSpec],
        filters: Mapping[str, FilterCallable] | None,
    ) -> _Key:
        return _Key(
            tuple(source.identity),
            immutable,
            self._extensions(extensions),
            tuple(
                sorted(
                    (name, _Identity(value)) for name, value in (filters or {}).items()
                )
            ),
        )

    def _record(self, events: Mapping[str, int]) -> None:
        try:
            self._observer.record("template_environment", events, len(self._entries))
        except Exception:
            return

    def _entry(
        self,
        source_value: TemplateSource,
        *,
        immutable: bool,
        extensions: Sequence[ExtensionSpec],
        filters: Mapping[str, FilterCallable] | None,
    ) -> _Entry:
        source = self._source(source_value)
        key = self._key(
            source,
            immutable=immutable,
            extensions=extensions,
            filters=filters,
        )
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                self._hits += 1
                self._record({"hit": 1})
                return cached
            self._misses += 1
            loader: jinja2.BaseLoader
            if isinstance(source, PackageResourceSource):
                loader = jinja2.PackageLoader(source.package, source.root)
            else:
                loader = jinja2.FileSystemLoader(source.root)
            environment = jinja2.Environment(
                loader=loader,
                extensions=tuple(extensions),
                enable_async=True,
                autoescape=jinja2.select_autoescape(),
                auto_reload=not immutable,
                # Explicit per-environment compiled cache: together with the
                # environment count bound this is a computable hard limit,
                # and 0 truly disables the cache.
                cache_size=self._cache_size,
            )
            environment.filters.update(dict(filters or {}))
            entry = _Entry(environment)
            if self._max_entries > 0:
                self._entries[key] = entry
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
                    self._evictions += 1
            self._record({"miss": 1})
            return entry

    def _load(
        self,
        template_path: TemplateSource,
        template_name: str,
        *,
        immutable: bool,
        extensions: Sequence[ExtensionSpec],
        filters: Mapping[str, FilterCallable] | None,
    ) -> jinja2.Template:
        entry = self._entry(
            template_path,
            immutable=immutable,
            extensions=extensions,
            filters=filters,
        )
        with entry.load_lock:
            return entry.environment.get_template(template_name)

    async def render(
        self,
        template_path: TemplateSource,
        template_name: str,
        variables: Mapping[str, Any],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        immutable: bool = False,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str:
        try:
            template = await self._worker.run_sync(
                partial(
                    self._load,
                    template_path,
                    template_name,
                    immutable=immutable,
                    extensions=tuple(extensions),
                    filters=dict(filters or {}),
                )
            )
            return await template.render_async(**dict(variables))
        except RenderingError:
            raise
        except Exception as error:
            raise PreparationError(
                "Template rendering failed.",
                source=error,
            ) from error

    async def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._record({})

    def invalidate(self, template_path: TemplateSource) -> int:
        source = self._source(template_path)
        identity = tuple(source.identity)
        with self._lock:
            keys = [key for key in self._entries if key.source == identity]
            for key in keys:
                del self._entries[key]
            self._record({})
        return len(keys)

    def stats(self) -> TemplateEnvironmentCacheStats:
        with self._lock:
            return TemplateEnvironmentCacheStats(
                entries=len(self._entries),
                max_entries=self._max_entries,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )


__all__ = ["JinjaTemplateCompiler"]
