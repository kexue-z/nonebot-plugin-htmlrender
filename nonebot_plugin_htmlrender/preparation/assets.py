"""Canonical matching for in-memory prepared assets."""

from __future__ import annotations

from html import unescape
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urljoin, urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import PreparedAsset


class _DefaultBase:
    __slots__ = ()


_DEFAULT_BASE = _DefaultBase()


def resolve_document_reference(base_url: str | None, reference: str) -> str:
    """Resolve a document reference only for hierarchical supported base URLs."""

    normalized = unescape(reference).strip().strip("'\"")
    if not normalized or base_url is None:
        return normalized
    scheme = urlsplit(base_url).scheme.lower()
    if scheme not in {"file", "http", "https"}:
        return normalized
    resolved, _ = urldefrag(urljoin(base_url, normalized))
    return resolved


class PreparedAssetIndex:
    """Index prepared assets by exact and base-resolved source identifiers."""

    def __init__(
        self,
        assets: Iterable[PreparedAsset],
        *,
        base_url: str | None = None,
    ) -> None:
        self.base_url = base_url
        self._exact: dict[str, PreparedAsset] = {}
        self._canonical: dict[str, PreparedAsset] = {}
        for asset in assets:
            self.add(asset)

    def add(self, asset: PreparedAsset) -> None:
        """Index one more asset with the same duplicate checks as construction."""
        source = unescape(asset.source).strip()
        if not source:
            raise ValueError("PreparedAsset source must not be empty")
        if source in self._exact:
            raise ValueError(
                f"PreparedAsset source {source!r} was supplied more than once"
            )
        self._exact[source] = asset
        canonical = resolve_document_reference(self.base_url, source)
        existing = self._canonical.get(canonical)
        if existing is not None and existing.source != source:
            raise ValueError(
                "PreparedAsset sources resolve to the same canonical URL: "
                f"{existing.source!r} and {source!r}"
            )
        self._canonical[canonical] = asset

    def match(
        self,
        reference: str,
        *,
        base_url: str | None | _DefaultBase = _DEFAULT_BASE,
    ) -> PreparedAsset | None:
        normalized = unescape(reference).strip().strip("'\"")
        exact = self._exact.get(normalized)
        if exact is not None:
            return exact
        resolved_base = (
            self.base_url if isinstance(base_url, _DefaultBase) else base_url
        )
        canonical = resolve_document_reference(resolved_base, normalized)
        return self._canonical.get(canonical)


__all__ = ["PreparedAssetIndex", "resolve_document_reference"]
