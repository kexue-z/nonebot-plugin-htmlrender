"""Logical package and filesystem resource sources.

Package resources are addressed by stable logical names and never exposed as
filesystem paths.  Filesystem resources retain their concrete path so callers
can opt into revalidation where appropriate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import PackageResourceRef


def _logical_parts(name: str | PurePosixPath) -> tuple[str, ...]:
    logical = PurePosixPath(str(name))
    parts = logical.parts
    if (
        not parts
        or logical.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Invalid logical resource name: {name!r}")
    return parts


@dataclass(frozen=True, slots=True)
class PackageResourceSource:
    package: str
    root: str = ""

    def __post_init__(self) -> None:
        if self.root:
            object.__setattr__(
                self,
                "root",
                PurePosixPath(*_logical_parts(self.root)).as_posix(),
            )

    @property
    def identity(self) -> tuple[str, str, str]:
        return ("package", self.package, self.root)

    def resource(self, name: str | PurePosixPath) -> PackageResourceRef:
        parts = _logical_parts(name)
        logical = (
            PurePosixPath(self.root, *parts) if self.root else PurePosixPath(*parts)
        )
        return PackageResourceRef(self.package, logical.as_posix())


@dataclass(frozen=True, slots=True)
class FilesystemResourceSource:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    @property
    def identity(self) -> tuple[str, str]:
        return ("filesystem", str(self.root))

    def resource(self, name: str | PurePosixPath) -> Path:
        parts = _logical_parts(name)
        candidate = self.root.joinpath(*parts).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"Resource escapes filesystem root: {name!r}") from error
        return candidate


__all__ = [
    "FilesystemResourceSource",
    "PackageResourceSource",
]
