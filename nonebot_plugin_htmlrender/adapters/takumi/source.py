from __future__ import annotations

from dataclasses import dataclass, replace
from html import unescape
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    PreparedHtml,
    PreparedStylesheet,
    RenderRequirement,
)
from nonebot_plugin_htmlrender.preparation.assets import PreparedAssetIndex
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.references import (
    css_at_rules,
    css_resource_references,
)
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode

from .errors import TakumiResourceError, TakumiUnsupportedError
from .types import (
    ImageCacheMode,
    TakumiImageResource,
)
from .validation import ensure_native_identifier, ensure_utf8

_MISSING = object()

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nonebot_plugin_htmlrender.preparation.models import DocumentStructureSnapshot
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources


@dataclass(frozen=True, slots=True)
class TakumiDocument:
    """Executor-ready document with only referenced images supplied in memory."""

    html: str
    stylesheets: tuple[str, ...]
    images: tuple[TakumiImageResource, ...]


@dataclass(frozen=True, slots=True)
class _ImageCandidate:
    asset: PreparedAsset
    cache: ImageCacheMode
    explicit: bool


def normalize_image_input(image: object, *, field: str) -> TakumiImageResource:
    """Normalize adapter, upstream, tuple, and promised duck image values."""

    if isinstance(image, TakumiImageResource):
        src = image.src
        data = image.data
        cache = image.cache
    elif isinstance(image, tuple):
        if len(image) != 2:
            raise TypeError(f"{field} must contain exactly (str, bytes).")
        src, data = image
        cache = "auto"
    else:
        src = getattr(image, "src", _MISSING)
        data = getattr(image, "data", _MISSING)
        if src is _MISSING or data is _MISSING:
            raise TypeError(
                f"{field} must be TakumiImageResource, (src, bytes), an upstream "
                "ImageResource, or expose `src` and `data` attributes."
            )
        cache = getattr(image, "cache", "auto")

    if not isinstance(src, str):
        raise TypeError(f"{field}.src must be str, got {type(src).__name__}.")
    ensure_native_identifier(src, field=f"{field}.src")
    if not isinstance(data, bytes):
        raise TypeError(f"{field}.data must be bytes, got {type(data).__name__}.")
    if cache not in {"auto", "none"}:
        raise ValueError(f"{field}.cache must be 'auto' or 'none'.")
    return TakumiImageResource(
        src=src,
        data=data,
        cache="auto" if cache == "auto" else "none",
    )


def _merge_image_candidates(
    prepared: PreparedHtml,
    images: Sequence[object] | None,
    *,
    document_base: str | None,
) -> tuple[PreparedAssetIndex, dict[str, _ImageCandidate]]:
    candidates: dict[str, _ImageCandidate] = {}

    def _insert(candidate: _ImageCandidate) -> None:
        source = candidate.asset.source
        existing = candidates.get(source)
        if existing is None:
            candidates[source] = candidate
            return
        if existing.asset.data != candidate.asset.data:
            raise TakumiResourceError(
                f"Takumi image source {source!r} has conflicting byte payloads."
            )
        if (
            existing.explicit
            and candidate.explicit
            and existing.cache != candidate.cache
        ):
            raise TakumiResourceError(
                f"Takumi image source {source!r} has conflicting cache modes."
            )
        if candidate.explicit:
            candidates[source] = candidate

    for index, asset in enumerate(prepared.assets):
        if not isinstance(asset.source, str):
            raise TypeError(
                "prepared.assets"
                f"[{index}].source must be str, got {type(asset.source).__name__}."
            )
        ensure_native_identifier(
            asset.source,
            field=f"prepared.assets[{index}].source",
        )
        if not isinstance(asset.data, bytes):
            raise TypeError(
                "prepared.assets"
                f"[{index}].data must be bytes, got {type(asset.data).__name__}."
            )
        _insert(_ImageCandidate(asset=asset, cache="auto", explicit=False))

    for index, image in enumerate(images or ()):
        normalized = normalize_image_input(image, field=f"images[{index}]")
        _insert(
            _ImageCandidate(
                asset=PreparedAsset(source=normalized.src, data=normalized.data),
                cache=normalized.cache,
                explicit=True,
            )
        )

    try:
        asset_index = PreparedAssetIndex(
            (candidate.asset for candidate in candidates.values()),
            base_url=document_base,
        )
    except ValueError as error:
        raise TakumiResourceError(
            "Takumi resource indexing failed.",
            source=error,
        ) from error
    return asset_index, candidates


def _normalize_reference(value: str, *, field: str) -> str:
    reference = unescape(value).strip().strip("'\"")
    ensure_native_identifier(reference, field=field)
    return reference


def _does_not_need_materialization(reference: str) -> bool:
    lowered = reference.lower()
    return not reference or lowered.startswith("data:") or reference.startswith("#")


def _validate_stylesheet(stylesheet: PreparedStylesheet, *, field: str) -> None:
    ensure_utf8(stylesheet.css, field=f"{field}.css")
    if stylesheet.media is not None:
        raise TakumiUnsupportedError(
            f"{field}.media={stylesheet.media!r} cannot be represented by Takumi; "
            "remove the media condition or use Playwright."
        )
    at_rules = frozenset(css_at_rules(stylesheet.css))
    if "import" in at_rules:
        raise TakumiUnsupportedError(
            f"{field} contains CSS @import, which Takumi cannot resolve; inline "
            "the imported stylesheet."
        )
    if "font-face" in at_rules:
        raise TakumiUnsupportedError(
            f"{field} contains @font-face, which Takumi cannot load; register font "
            "bytes through the Takumi extension or "
            "render.provider_config.fonts."
        )


def image_resource_keys(images: Sequence[object] | None) -> frozenset[str]:
    """Return normalized source keys for every supported image input form."""

    return frozenset(
        normalize_image_input(image, field=f"images[{index}]").src
        for index, image in enumerate(images or ())
    )


def _inspect_document(
    prepared: PreparedHtml,
) -> tuple[DocumentStructureSnapshot, str | None]:
    ensure_utf8(prepared.html, field="prepared.html")
    if not prepared.html.strip():
        raise ValueError("HTML content cannot be empty")
    snapshot = prepared.structure
    document_base = prepared.document_base.resolve()
    if snapshot.has_script or RenderRequirement.JAVASCRIPT in prepared.requirements:
        raise TakumiUnsupportedError(
            "Takumi does not execute JavaScript; remove <script> elements or use "
            "the Playwright backend."
        )
    if snapshot.linked_stylesheets:
        raise TakumiUnsupportedError(
            "Takumi cannot load <link rel='stylesheet'> resources; provide CSS "
            "content through PreparedStylesheet or an explicit stylesheet string."
        )
    return snapshot, document_base


async def materialize_takumi_document(
    prepared: PreparedHtml,
    *,
    resources: ProviderResources,
    stylesheets: Sequence[str] = (),
    images: Sequence[object] | None = None,
    resolve_mode: ResourceResolveMode | None = None,
) -> TakumiDocument:
    """Apply the effective resource mode before native Takumi validation."""

    # Staging changes assets and stylesheets but never the markup, so one
    # inspection serves both the staging step and the final document build.
    snapshot, document_base = _inspect_document(prepared)
    _, candidates = _merge_image_candidates(
        prepared,
        images,
        document_base=document_base,
    )
    staged = replace(
        prepared,
        assets=tuple(candidate.asset for candidate in candidates.values()),
    )
    if stylesheets:
        staged = replace(
            staged,
            stylesheets=(
                *staged.stylesheets,
                *(
                    PreparedStylesheet(css=css, base_url=document_base)
                    for css in stylesheets
                ),
            ),
        )
    mode = resolve_mode or resources.strategy.resolve_mode
    if mode is ResourceResolveMode.OFF:
        return _build_takumi_document(
            staged,
            snapshot=snapshot,
            document_base=document_base,
            images=images,
            strict=False,
        )
    try:
        materialized = await materialize_local_assets(
            staged,
            resources=resources,
            strict=mode is ResourceResolveMode.STRICT,
        )
    except AssetMaterializationError as error:
        raise TakumiResourceError(
            "Takumi resource materialization failed.",
            source=error,
        ) from error
    return _build_takumi_document(
        materialized,
        snapshot=snapshot,
        document_base=document_base,
        images=images,
        strict=mode is ResourceResolveMode.STRICT,
    )


def prepare_takumi_document(
    prepared: PreparedHtml,
    *,
    stylesheets: Sequence[str] = (),
    images: Sequence[object] | None = None,
    strict: bool = True,
) -> TakumiDocument:
    """Validate and adapt one backend-neutral document for Takumi 0.2.0."""

    snapshot, document_base = _inspect_document(prepared)
    return _build_takumi_document(
        prepared,
        snapshot=snapshot,
        document_base=document_base,
        stylesheets=stylesheets,
        images=images,
        strict=strict,
    )


def _build_takumi_document(
    prepared: PreparedHtml,
    *,
    snapshot: DocumentStructureSnapshot,
    document_base: str | None,
    stylesheets: Sequence[str] = (),
    images: Sequence[object] | None = None,
    strict: bool = True,
) -> TakumiDocument:
    shared_stylesheets = tuple(prepared.stylesheets)
    backend_stylesheets = tuple(
        PreparedStylesheet(css=css, base_url=document_base) for css in stylesheets
    )
    all_stylesheets = (*shared_stylesheets, *backend_stylesheets)
    for index, stylesheet in enumerate(all_stylesheets):
        _validate_stylesheet(stylesheet, field=f"stylesheets[{index}]")

    asset_index, candidates = _merge_image_candidates(
        prepared,
        images,
        document_base=document_base,
    )
    references: list[tuple[str, str | None, str]] = [
        (reference, document_base, f"prepared.html.references[{index}]")
        for index, reference in enumerate(snapshot.references)
    ]
    for stylesheet_index, stylesheet in enumerate(all_stylesheets):
        references.extend(
            (
                reference,
                stylesheet.base_url,
                f"stylesheets[{stylesheet_index}].references[{reference_index}]",
            )
            for reference_index, reference in enumerate(
                css_resource_references(stylesheet.css)
            )
        )

    selected: dict[str, TakumiImageResource] = {}
    unresolved: list[str] = []
    for raw_reference, base_url, field in references:
        reference = _normalize_reference(raw_reference, field=field)
        if _does_not_need_materialization(reference):
            continue
        matched = asset_index.match(reference, base_url=base_url)
        if matched is None:
            unresolved.append(reference)
            continue
        candidate = candidates[matched.source]
        resource = TakumiImageResource(
            src=reference,
            data=matched.data,
            cache=candidate.cache,
        )
        existing = selected.get(reference)
        if existing is not None and existing != resource:
            raise TakumiResourceError(
                f"Takumi resource key {reference!r} resolves to conflicting assets "
                "under different document or stylesheet bases. Use distinct source "
                "keys or inline one resource."
            )
        selected.setdefault(reference, resource)

    if unresolved and strict:
        unique = tuple(dict.fromkeys(unresolved))
        preview = ", ".join(repr(value) for value in unique[:3])
        suffix = " ..." if len(unique) > 3 else ""
        raise TakumiResourceError(
            "Takumi performs no network or filesystem fetches. Materialize every "
            f"referenced image as bytes; unresolved resources: {preview}{suffix}"
        )

    return TakumiDocument(
        html=prepared.html,
        stylesheets=tuple(stylesheet.css for stylesheet in all_stylesheets),
        images=tuple(selected.values()),
    )


__all__ = [
    "TakumiDocument",
    "image_resource_keys",
    "materialize_takumi_document",
    "normalize_image_input",
    "prepare_takumi_document",
]
