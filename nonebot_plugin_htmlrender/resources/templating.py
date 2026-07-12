from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from jinja2.ext import Extension

from .source import FilesystemResourceSource, PackageResourceSource

FilterCallable: TypeAlias = Callable[..., Any]
ExtensionSpec: TypeAlias = str | type[Extension]
TemplateSource: TypeAlias = (
    str | Path | FilesystemResourceSource | PackageResourceSource
)


@dataclass(frozen=True, slots=True)
class TemplateEnvironmentCacheStats:
    entries: int
    max_entries: int
    hits: int
    misses: int
    evictions: int


__all__ = [
    "ExtensionSpec",
    "FilterCallable",
    "TemplateEnvironmentCacheStats",
    "TemplateSource",
]
