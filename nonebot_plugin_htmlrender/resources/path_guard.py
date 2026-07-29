"""Canonical local-path access policy shared by every resource entry point.

The sensitive-path denylist is deliberately non-exhaustive. It is a minimal,
cross-platform defense-in-depth backstop for explicit ``allow_any`` operation,
not a trust boundary or filesystem sandbox. Callers that handle attacker-controlled
paths must keep using an allowlist.

Validation canonicalizes symlinks before applying the policy, but a path can still be
replaced between validation and a later open/upload. Callers needing protection from
an adversarial local filesystem must use descriptor-relative or handle-based I/O.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


def _sensitive_root_candidates(
    *,
    platform: str,
    home: Path,
    environment: Mapping[str, str],
) -> tuple[Path, ...]:
    roots = [
        home / ".ssh",
        home / ".aws",
        home / ".gnupg",
        home / ".kube",
        home / ".docker" / "config.json",
        home / ".netrc",
    ]
    if platform == "nt":
        system_root = Path(environment.get("SYSTEMROOT", "C:/Windows"))
        roots.extend(
            system_root / "System32" / "config" / hive
            for hive in ("SAM", "SECURITY", "SYSTEM")
        )
        if appdata := environment.get("APPDATA"):
            roots.extend((Path(appdata) / "gnupg", Path(appdata) / "gcloud"))
    else:
        roots.extend(Path(root) for root in ("/etc", "/proc", "/sys", "/root"))
    return tuple(roots)


def _build_sensitive_roots() -> tuple[Path, ...]:
    roots = _sensitive_root_candidates(
        platform=os.name,
        home=Path.home(),
        environment=os.environ,
    )
    return tuple(dict.fromkeys(root.expanduser().resolve() for root in roots))


_SENSITIVE_ROOTS = _build_sensitive_roots()
_SENSITIVE_FILE_NAMES = frozenset({".env", ".netrc"})


def is_subpath(path: Path, root: Path) -> bool:
    """Return whether canonical ``path`` is ``root`` or one of its descendants."""

    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sensitive_local_root(path: Path) -> Path | None:
    if path.name in _SENSITIVE_FILE_NAMES or path.name.startswith(".env."):
        return path
    return next((root for root in _SENSITIVE_ROOTS if is_subpath(path, root)), None)


def sensitive_local_root(path: Path) -> Path | None:
    """Return the minimal sensitive root containing a canonicalized ``path``."""

    return _sensitive_local_root(path.expanduser().resolve())


def validate_local_access(
    path: Path,
    *,
    allowed_roots: Sequence[Path],
    allow_any: bool,
    on_deny: Callable[[str], Exception],
) -> Path:
    """Canonicalize ``path`` and enforce the shared local-access policy."""

    normalized_path = path.expanduser().resolve()
    normalized_roots = tuple(root.expanduser().resolve() for root in allowed_roots)
    if allow_any:
        denied_root = _sensitive_local_root(normalized_path)
        if denied_root is not None:
            raise on_deny(
                f"Refused local access to sensitive local path {normalized_path!s} "
                f"under {denied_root!s}; allow_any is not a filesystem sandbox."
            )
        return normalized_path
    if not normalized_roots:
        raise on_deny("Refused local access without an allowed root.")
    if any(is_subpath(normalized_path, root) for root in normalized_roots):
        return normalized_path
    roots = ", ".join(str(root) for root in normalized_roots)
    raise on_deny(f"Local path {normalized_path!s} is outside allowed roots: {roots}.")


__all__ = ["is_subpath", "sensitive_local_root", "validate_local_access"]
