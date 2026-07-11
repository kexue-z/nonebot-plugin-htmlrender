from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation import PreparedHtml, RenderRequirement

from .errors import TakumiResourceError, TakumiUnsupportedError
from .types import TakumiImageResource

if TYPE_CHECKING:
    from collections.abc import Sequence

_STYLESHEET_LINK_RE = re.compile(
    r"<link\b(?=[^>]*\brel\s*=\s*(?:"
    r"['\"][^'\"]*\bstylesheet\b[^'\"]*['\"]|"
    r"[^\s>]*\bstylesheet\b))[^>]*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_CSS_IMPORT_RE = re.compile(r"@import\b", flags=re.IGNORECASE)
_FONT_FACE_RE = re.compile(r"@font-face\b", flags=re.IGNORECASE)
_IMAGE_TAG_RE = re.compile(r"<(?:img|image)\b[^>]*>", re.IGNORECASE | re.DOTALL)
_RESOURCE_ATTR_RE = re.compile(
    r"\b(?:src|href|xlink:href)\s*=\s*"
    r"(?:'(?P<single>[^']*)'|\"(?P<double>[^\"]*)\"|(?P<bare>[^\s>]+))",
    flags=re.IGNORECASE | re.DOTALL,
)
_CSS_URL_RE = re.compile(
    r"url\(\s*(?:'(?P<single>[^']*)'|\"(?P<double>[^\"]*)\"|(?P<bare>[^)]*))\s*\)",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class TakumiDocument:
    """Executor-ready document with every external image supplied in memory."""

    markup: str
    stylesheets: tuple[str, ...]
    images: tuple[object, ...]


def _image_resource_key(image: object) -> str:
    if isinstance(image, TakumiImageResource):
        return image.src
    if isinstance(image, tuple):
        if (
            len(image) == 2
            and isinstance(image[0], str)
            and isinstance(image[1], bytes)
        ):
            return image[0]
        raise TypeError("Takumi image tuples must contain exactly (str, bytes).")
    src = getattr(image, "src", None)
    data = getattr(image, "data", None)
    if isinstance(src, str) and isinstance(data, bytes):
        return src
    raise TypeError(
        "Takumi images must be TakumiImageResource, (src, bytes), or expose "
        "string `src` and bytes `data` attributes."
    )


def image_resource_keys(images: Sequence[object] | None) -> frozenset[str]:
    if not images:
        return frozenset()
    return frozenset(_image_resource_key(image) for image in images)


def _merge_images(
    prepared: PreparedHtml,
    images: Sequence[object] | None,
) -> tuple[object, ...]:
    merged: list[object] = [
        TakumiImageResource(asset.source, asset.data) for asset in prepared.assets
    ]
    merged.extend(images or ())

    seen: set[str] = set()
    for image in merged:
        key = _image_resource_key(image)
        if key in seen:
            raise TakumiResourceError(
                f"Takumi image source {key!r} was supplied more than once."
            )
        seen.add(key)
    return tuple(merged)


def _is_available_reference(value: str, image_keys: frozenset[str]) -> bool:
    reference = unescape(value).strip().strip("'\"")
    if not reference:
        return True
    return (
        reference.lower().startswith("data:")
        or reference.startswith("#")
        or reference in image_keys
    )


def _html_image_references(markup: str) -> list[str]:
    references: list[str] = []
    for tag in _IMAGE_TAG_RE.findall(markup):
        attribute = _RESOURCE_ATTR_RE.search(tag)
        if attribute is not None:
            references.append(
                attribute.group("single")
                or attribute.group("double")
                or attribute.group("bare")
                or ""
            )
    return references


def _css_references(css: str) -> list[str]:
    return [
        (match.group("single") or match.group("double") or match.group("bare") or "")
        for match in _CSS_URL_RE.finditer(css)
    ]


def prepare_takumi_document(
    prepared: PreparedHtml,
    *,
    stylesheets: Sequence[str] = (),
    images: Sequence[object] | None = None,
) -> TakumiDocument:
    """Validate a shared prepared document against Takumi's native constraints."""
    if not prepared.markup.strip():
        raise ValueError("HTML content cannot be empty")
    if RenderRequirement.JAVASCRIPT in prepared.requirements:
        raise TakumiUnsupportedError(
            "Takumi does not execute JavaScript; remove <script> elements or use "
            "the Playwright backend."
        )
    if _STYLESHEET_LINK_RE.search(prepared.markup):
        raise TakumiUnsupportedError(
            "Takumi cannot load <link rel='stylesheet'> resources; provide CSS "
            "content as a <style> block or an explicit stylesheet string."
        )

    all_stylesheets = (*prepared.stylesheets, *stylesheets)
    for css in all_stylesheets:
        if _CSS_IMPORT_RE.search(css):
            raise TakumiUnsupportedError(
                "Takumi cannot resolve CSS @import; inline the imported stylesheet."
            )
        if _FONT_FACE_RE.search(css):
            raise TakumiUnsupportedError(
                "Takumi does not load @font-face URLs; register font bytes through "
                "render_takumi.fonts instead."
            )

    merged_images = _merge_images(prepared, images)
    keys = image_resource_keys(merged_images)
    references = _html_image_references(prepared.markup)
    references.extend(_css_references(prepared.markup))
    for css in all_stylesheets:
        references.extend(_css_references(css))

    unresolved = sorted(
        {
            unescape(reference).strip()
            for reference in references
            if not _is_available_reference(reference, keys)
        }
    )
    if unresolved:
        preview = ", ".join(repr(value) for value in unresolved[:3])
        suffix = " ..." if len(unresolved) > 3 else ""
        raise TakumiResourceError(
            "Takumi performs no network or filesystem fetches. Supply exact source "
            f"keys with image bytes; unresolved resources: {preview}{suffix}"
        )

    return TakumiDocument(
        markup=prepared.markup,
        stylesheets=all_stylesheets,
        images=merged_images,
    )


__all__ = [
    "TakumiDocument",
    "image_resource_keys",
    "prepare_takumi_document",
]
