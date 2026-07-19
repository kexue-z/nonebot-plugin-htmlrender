"""Shared document materialization built on the preparation-time snapshot.

Every consumer (Playwright, Takumi, HTMLKit, the local asset materializer)
derives the canonical document base and markup from here. Canonicalizing the
``<base>`` element and injecting head content are pure string splices driven
by :class:`DocumentStructureSnapshot` offsets — the markup is never parsed
again after preparation.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import PreparedHtml, PreparedStylesheet


@dataclass(frozen=True, slots=True)
class ResolvedDocument:
    """Canonical execution view of one prepared document."""

    markup: str
    document_base: str | None
    base_href: str | None
    references: tuple[str, ...]


def replace_tag_attribute_value(raw: str, name: str, value: str) -> str:
    """Replace one real tag attribute value without rebuilding the tag."""
    cursor = 1
    length = len(raw)
    while cursor < length and not raw[cursor].isspace() and raw[cursor] not in ">/":
        cursor += 1

    replacements: list[tuple[int, int, str]] = []
    while cursor < length:
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] in ">/":
            break
        attribute_start = cursor
        while (
            cursor < length and not raw[cursor].isspace() and raw[cursor] not in "=/>"
        ):
            cursor += 1
        attribute_name = raw[attribute_start:cursor].lower()
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] != "=":
            continue
        cursor += 1
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length:
            break
        if raw[cursor] in {'"', "'"}:
            quote = raw[cursor]
            value_start = cursor + 1
            cursor = value_start
            while cursor < length and raw[cursor] != quote:
                cursor += 1
            value_end = cursor
            cursor += cursor < length
        else:
            value_start = cursor
            while cursor < length and not raw[cursor].isspace() and raw[cursor] != ">":
                cursor += 1
            value_end = cursor
        if attribute_name == name:
            replacements.append((value_start, value_end, escape(value, quote=True)))

    for start, end, replacement in reversed(replacements):
        raw = f"{raw[:start]}{replacement}{raw[end:]}"
    return raw


def _stylesheet_blocks(
    prepared: PreparedHtml,
    stylesheet_css: Callable[[PreparedStylesheet], str] | None,
) -> str:
    blocks: list[str] = []
    for stylesheet in prepared.stylesheets:
        # Embedded styles already occur in the original document. Re-injecting
        # them would change cascade order and drop attributes such as media.
        if stylesheet.embedded:
            continue
        css = stylesheet_css(stylesheet) if stylesheet_css else stylesheet.css
        media = (
            f' media="{escape(stylesheet.media, quote=True)}"'
            if stylesheet.media
            else ""
        )
        blocks.append(f"<style{media}>{css}</style>")
    return "".join(blocks)


def resolve_document(
    prepared: PreparedHtml,
    *,
    fallback_base_url: str | None = None,
    allow_file_base_href: bool = False,
    inject_base: bool = False,
    stylesheet_css: Callable[[PreparedStylesheet], str] | None = None,
    inject_stylesheets: bool = True,
) -> ResolvedDocument:
    """Materialize the canonical markup, document base, and references.

    ``fallback_base_url`` is the execution-time document URL used when
    preparation had no base. ``inject_base`` canonicalizes a declared
    ``<base>`` to the resolved base and, when none is declared, injects one
    for http(s) bases (``allow_file_base_href`` extends this to ``file://``,
    the file-base policy). ``stylesheet_css`` lets an adapter transform each
    non-embedded stylesheet before injection.
    """
    structure = prepared.structure
    declared = prepared.document_base.declared_href
    document_base = prepared.document_base.resolve(fallback_base_url)
    base_href = (
        document_base
        if inject_base
        and document_base
        and document_base != "about:blank"
        and (
            declared is not None
            or document_base.startswith(("http://", "https://"))
            or (allow_file_base_href and document_base.startswith("file://"))
        )
        else None
    )

    head_content = ""
    if base_href is not None and structure.base_tag is None:
        head_content += f'<base href="{escape(base_href, quote=True)}">'
    if inject_stylesheets:
        head_content += _stylesheet_blocks(prepared, stylesheet_css)

    splices: list[tuple[int, int, str]] = []
    if base_href is not None and structure.base_tag is not None:
        start, end, raw = structure.base_tag
        rewritten = replace_tag_attribute_value(raw, "href", base_href)
        if rewritten != raw:
            splices.append((start, end, rewritten))
    if head_content:
        if structure.head_open_end is not None:
            splices.append(
                (structure.head_open_end, structure.head_open_end, head_content)
            )
        elif structure.doctype_end is not None:
            splices.append(
                (
                    structure.doctype_end,
                    structure.doctype_end,
                    f"<head>{head_content}</head>",
                )
            )
        else:
            splices.append((0, 0, f"<head>{head_content}</head>"))

    markup = prepared.html
    for start, end, replacement in sorted(splices, reverse=True):
        markup = f"{markup[:start]}{replacement}{markup[end:]}"

    return ResolvedDocument(
        markup=markup,
        document_base=document_base,
        base_href=base_href,
        references=structure.references,
    )


__all__ = [
    "ResolvedDocument",
    "replace_tag_attribute_value",
    "resolve_document",
]
