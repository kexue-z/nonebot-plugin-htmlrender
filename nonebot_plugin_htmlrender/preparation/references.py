"""Token-aware HTML and CSS reference discovery without rewriting source text."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import TYPE_CHECKING

from .models import PreparedStylesheet

if TYPE_CHECKING:
    from collections.abc import Callable

_RESOURCE_ATTRIBUTES: dict[str, frozenset[str]] = {
    "audio": frozenset({"src"}),
    "embed": frozenset({"src"}),
    "iframe": frozenset({"src"}),
    "image": frozenset({"href", "xlink:href"}),
    "img": frozenset({"src", "srcset"}),
    "input": frozenset({"src"}),
    "link": frozenset({"href"}),
    "object": frozenset({"data"}),
    "script": frozenset({"src"}),
    "source": frozenset({"src", "srcset"}),
    "track": frozenset({"src"}),
    "use": frozenset({"href", "xlink:href"}),
    "video": frozenset({"poster", "src"}),
}
_CSS_SPACE = frozenset(" \t\r\n\f")
_CSS_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]")


def _css_unescape_string(value: str) -> str:
    # Full CSS escape interpretation belongs to the browser/native parser.  For
    # resource classification we only collapse escaped quote/backslash pairs.
    return re.sub(r"\\([\\'\"])", r"\1", value)


@dataclass(frozen=True, slots=True)
class _ReferenceToken:
    start: int
    end: int
    value: str


def _consume_css_string(css: str, start: int) -> tuple[int, int]:
    quote = css[start]
    cursor = start + 1
    while cursor < len(css):
        if css[cursor] == "\\":
            cursor = min(cursor + 2, len(css))
        elif css[cursor] == quote:
            return cursor, cursor + 1
        else:
            cursor += 1
    return len(css), len(css)


def _css_reference_tokens(css: str) -> tuple[_ReferenceToken, ...]:
    tokens: list[_ReferenceToken] = []

    index = 0
    length = len(css)
    while index < length:
        if css.startswith("/*", index):
            end = css.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue

        char = css[index]
        if char in {'"', "'"}:
            _, index = _consume_css_string(css, index)
            continue

        if css[index : index + 3].lower() == "url" and (
            index == 0 or _CSS_IDENTIFIER.fullmatch(css[index - 1]) is None
        ):
            cursor = index + 3
            while cursor < length and css[cursor] in _CSS_SPACE:
                cursor += 1
            if cursor < length and css[cursor] == "(":
                cursor += 1
                while cursor < length and css[cursor] in _CSS_SPACE:
                    cursor += 1
                quote = (
                    css[cursor]
                    if cursor < length and css[cursor] in {'"', "'"}
                    else None
                )
                if quote is not None:
                    start = cursor + 1
                    end, cursor = _consume_css_string(css, cursor)
                else:
                    start = cursor
                    while cursor < length:
                        if css[cursor] == "\\":
                            cursor = min(cursor + 2, length)
                        elif css[cursor] == ")":
                            break
                        else:
                            cursor += 1
                    end = cursor
                    while start < end and css[start] in _CSS_SPACE:
                        start += 1
                    while end > start and css[end - 1] in _CSS_SPACE:
                        end -= 1
                value = css[start:end]
                if value:
                    tokens.append(
                        _ReferenceToken(
                            start=start,
                            end=end,
                            value=_css_unescape_string(value),
                        )
                    )
                close = css.find(")", cursor)
                index = length if close < 0 else close + 1
                continue

        if css[index : index + 7].lower() == "@import" and (
            index + 7 == length or _CSS_IDENTIFIER.fullmatch(css[index + 7]) is None
        ):
            cursor = index + 7
            while cursor < length and css[cursor] in _CSS_SPACE:
                cursor += 1
            if cursor < length and css[cursor] in {'"', "'"}:
                start = cursor + 1
                end, cursor = _consume_css_string(css, cursor)
                value = css[start:end]
                if value:
                    tokens.append(
                        _ReferenceToken(
                            start=start,
                            end=end,
                            value=_css_unescape_string(value),
                        )
                    )
                index = cursor
                continue
            # Let the url() scanner handle ``@import url(...)`` exactly once.
            index = cursor
            continue

        index += 1
    return tuple(tokens)


def css_resource_references(css: str) -> tuple[str, ...]:
    """Return url()/@import references while skipping comments and strings."""

    return tuple(token.value for token in _css_reference_tokens(css))


def css_at_rules(css: str) -> tuple[str, ...]:
    """Return real CSS at-rule names while skipping comments and strings."""

    rules: list[str] = []
    index = 0
    length = len(css)
    while index < length:
        if css.startswith("/*", index):
            end = css.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if css[index] in {'"', "'"}:
            _, index = _consume_css_string(css, index)
            continue
        if css[index : index + 3].lower() == "url" and (
            index == 0 or _CSS_IDENTIFIER.fullmatch(css[index - 1]) is None
        ):
            cursor = index + 3
            while cursor < length and css[cursor] in _CSS_SPACE:
                cursor += 1
            if cursor < length and css[cursor] == "(":
                close = cursor + 1
                quote: str | None = None
                while close < length:
                    char = css[close]
                    if quote is not None:
                        if char == "\\":
                            close += 2
                            continue
                        if char == quote:
                            quote = None
                    elif char in {'"', "'"}:
                        quote = char
                    elif char == ")":
                        close += 1
                        break
                    close += 1
                index = close
                continue
        if css[index] == "@":
            cursor = index + 1
            while cursor < length and _CSS_IDENTIFIER.fullmatch(css[cursor]):
                cursor += 1
            if cursor > index + 1:
                rules.append(css[index + 1 : cursor].lower())
                index = cursor
                continue
        index += 1
    return tuple(rules)


def rewrite_css_references(
    css: str,
    rewrite: Callable[[str], str | None],
) -> str:
    """Rewrite real CSS resource tokens without touching comments or strings."""

    replacements: list[tuple[int, int, str]] = []
    for token in _css_reference_tokens(css):
        replacement = rewrite(token.value)
        if replacement is not None and replacement != token.value:
            replacements.append((token.start, token.end, replacement))
    for start, end, replacement in reversed(replacements):
        css = f"{css[:start]}{replacement}{css[end:]}"
    return css


def _srcset_tokens(value: str) -> tuple[_ReferenceToken, ...]:
    tokens: list[_ReferenceToken] = []
    cursor = 0
    length = len(value)
    while cursor < length:
        while cursor < length and (value[cursor].isspace() or value[cursor] == ","):
            cursor += 1
        start = cursor
        is_data_url = value[start : start + 5].lower() == "data:"
        has_query = False
        comma_separator = False
        while cursor < length and not value[cursor].isspace():
            if value[cursor] == "?":
                has_query = True
            elif value[cursor] == "," and not is_data_url and not has_query:
                comma_separator = True
                break
            cursor += 1
        end = cursor
        if end > start:
            tokens.append(_ReferenceToken(start=start, end=end, value=value[start:end]))
        if comma_separator:
            cursor += 1
            continue

        parentheses = 0
        while cursor < length:
            char = value[cursor]
            if char == "(":
                parentheses += 1
            elif char == ")" and parentheses:
                parentheses -= 1
            elif char == "," and parentheses == 0:
                cursor += 1
                break
            cursor += 1
    return tuple(tokens)


def _srcset_references(value: str) -> tuple[str, ...]:
    return tuple(token.value for token in _srcset_tokens(value))


def _rewrite_srcset(value: str, rewrite: Callable[[str], str | None]) -> str:
    replacements: list[tuple[int, int, str]] = []
    for token in _srcset_tokens(value):
        replacement = rewrite(token.value)
        if replacement is not None and replacement != token.value:
            replacements.append((token.start, token.end, replacement))
    for start, end, replacement in reversed(replacements):
        value = f"{value[:start]}{replacement}{value[end:]}"
    return value


def _rewrite_start_tag(
    raw: str,
    *,
    tag: str,
    rewrite: Callable[[str], str | None],
) -> str:
    cursor = 1
    length = len(raw)
    while cursor < length and not raw[cursor].isspace() and raw[cursor] not in ">/":
        cursor += 1

    replacements: list[tuple[int, int, str]] = []
    resource_attributes = _RESOURCE_ATTRIBUTES.get(tag.lower(), ())
    while cursor < length:
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] in ">/":
            break
        name_start = cursor
        while (
            cursor < length and not raw[cursor].isspace() and raw[cursor] not in "=/>"
        ):
            cursor += 1
        name = raw[name_start:cursor].lower()
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

        value = raw[value_start:value_end]
        replacement: str | None = None
        if name == "style":
            replacement = rewrite_css_references(value, rewrite)
        elif name == "srcset" and name in resource_attributes:
            replacement = _rewrite_srcset(value, rewrite)
        elif name in resource_attributes:
            replacement = rewrite(value)
        if replacement is not None and replacement != value:
            replacements.append((value_start, value_end, replacement))

    for start, end, replacement in reversed(replacements):
        raw = f"{raw[:start]}{replacement}{raw[end:]}"
    return raw


class _ReferenceRewriter(HTMLParser):
    def __init__(self, html: str, rewrite: Callable[[str], str | None]) -> None:
        super().__init__(convert_charrefs=False)
        self.html = html
        self.rewrite = rewrite
        self.replacements: list[tuple[int, int, str]] = []
        self._in_style = False
        self._line_offsets = [0]
        self._line_offsets.extend(
            index + 1 for index, char in enumerate(html) if char == "\n"
        )

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def _rewrite_tag(self, tag: str) -> None:
        raw = self.get_starttag_text()
        if raw is None:
            return
        rewritten = _rewrite_start_tag(raw, tag=tag, rewrite=self.rewrite)
        if rewritten != raw:
            start = self._offset()
            self.replacements.append((start, start + len(raw), rewritten))

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        self._rewrite_tag(tag)
        if tag.lower() == "style":
            self._in_style = True

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        self._rewrite_tag(tag)

    def handle_data(self, data: str) -> None:
        if not self._in_style:
            return
        rewritten = rewrite_css_references(data, self.rewrite)
        if rewritten != data:
            start = self._offset()
            self.replacements.append((start, start + len(data), rewritten))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._in_style = False


def rewrite_html_references(
    html: str,
    rewrite: Callable[[str], str | None],
) -> str:
    """Rewrite references in real HTML tokens while preserving all other text."""

    parser = _ReferenceRewriter(html, rewrite)
    parser.feed(html)
    parser.close()
    for start, end, replacement in reversed(parser.replacements):
        html = f"{html[:start]}{replacement}{html[end:]}"
    return html


@dataclass(slots=True)
class HtmlReferenceSnapshot:
    references: list[str] = field(default_factory=list)
    stylesheets: list[PreparedStylesheet] = field(default_factory=list)
    linked_stylesheets: list[str] = field(default_factory=list)
    base_href: str | None = None
    has_script: bool = False
    base_tag: tuple[int, int, str] | None = None
    head_open_end: int | None = None
    doctype_end: int | None = None


class _ReferenceParser(HTMLParser):
    def __init__(self, *, base_url: str | None) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.snapshot = HtmlReferenceSnapshot()
        self._style_chunks: list[str] | None = None
        self._style_media: str | None = None
        self._base_href_seen = False
        self._line_offsets: list[int] = [0]
        self._fed_length = 0

    def feed(self, data: str) -> None:
        base = self._fed_length
        self._line_offsets.extend(
            base + offset + 1 for offset, char in enumerate(data) if char == "\n"
        )
        self._fed_length += len(data)
        super().feed(data)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def handle_decl(self, decl: str) -> None:
        if self.snapshot.doctype_end is None and decl.lower().startswith("doctype"):
            self.snapshot.doctype_end = self._offset() + len(decl) + 3

    def _handle_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        collect_style: bool,
    ) -> None:
        lowered_tag = tag.lower()
        normalized = {name.lower(): value or "" for name, value in attrs}
        if lowered_tag == "script":
            self.snapshot.has_script = True
        if lowered_tag == "head" and self.snapshot.head_open_end is None:
            raw = self.get_starttag_text()
            if raw is not None:
                self.snapshot.head_open_end = self._offset() + len(raw)
        if lowered_tag == "base" and not self._base_href_seen:
            # Per the HTML spec the first <base> element carrying an href
            # attribute sets the base, even when that href is empty; later
            # <base> elements are ignored. An explicit empty href resolves to
            # the document URL and stays distinct from an undeclared base.
            declared = normalized.get("href")
            if declared is not None:
                self._base_href_seen = True
                self.snapshot.base_href = declared
                raw = self.get_starttag_text()
                if raw is not None:
                    start = self._offset()
                    self.snapshot.base_tag = (start, start + len(raw), raw)
        if lowered_tag == "style" and collect_style:
            self._style_chunks = []
            self._style_media = normalized.get("media") or None
        if lowered_tag == "link" and "stylesheet" in {
            token.lower() for token in normalized.get("rel", "").split()
        }:
            href = normalized.get("href")
            if href:
                self.snapshot.linked_stylesheets.append(href)

        resource_attributes = _RESOURCE_ATTRIBUTES.get(lowered_tag, ())
        for name, raw_value in attrs:
            name = name.lower()
            value = raw_value or ""
            if not value:
                continue
            if name == "style":
                self.snapshot.references.extend(css_resource_references(value))
            elif name == "srcset" and name in resource_attributes:
                self.snapshot.references.extend(_srcset_references(value))
            elif name in resource_attributes:
                self.snapshot.references.append(value)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._handle_tag(tag, attrs, collect_style=True)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._handle_tag(tag, attrs, collect_style=False)

    def handle_data(self, data: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(f"&#{name};")

    def _flush_style(self) -> None:
        if self._style_chunks is None:
            return
        css = "".join(self._style_chunks)
        self.snapshot.stylesheets.append(
            PreparedStylesheet(
                css=css,
                base_url=self.base_url,
                embedded=True,
                media=self._style_media,
            )
        )
        self.snapshot.references.extend(css_resource_references(css))
        self._style_chunks = None
        self._style_media = None

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._flush_style()

    def close(self) -> None:
        super().close()
        self._flush_style()


def inspect_html_references(
    html: str,
    *,
    base_url: str | None = None,
) -> HtmlReferenceSnapshot:
    parser = _ReferenceParser(base_url=base_url)
    parser.feed(html)
    parser.close()
    return parser.snapshot


__all__ = [
    "HtmlReferenceSnapshot",
    "css_at_rules",
    "css_resource_references",
    "inspect_html_references",
    "rewrite_css_references",
    "rewrite_html_references",
]
