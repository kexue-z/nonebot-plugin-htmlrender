"""Adapt backend-neutral prepared documents for browser execution."""

from __future__ import annotations

from base64 import b64encode
from html import unescape
import mimetypes
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation import PreparedAsset, PreparedHtml

_ATTRIBUTE_URL_RE = re.compile(
    r"(?P<prefix>\b(?:src|href|poster|xlink:href)\s*=\s*)"
    r"(?:"
    r"(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)"
    r"|(?P<bare>[^\s>]+)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CSS_URL_RE = re.compile(
    r"url\(\s*(?:"
    r"(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)"
    r"|(?P<bare>[^)]*?)"
    r")\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)
_MEDIA_TYPE_RE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


def _asset_data_url(asset: PreparedAsset) -> str:
    media_type = asset.media_type or mimetypes.guess_type(asset.source)[0]
    media_type = media_type or "application/octet-stream"
    if _MEDIA_TYPE_RE.fullmatch(media_type) is None:
        raise ValueError(f"Invalid PreparedAsset media type: {media_type!r}")
    payload = b64encode(asset.data).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _asset_urls(assets: tuple[PreparedAsset, ...]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for asset in assets:
        if not asset.source:
            raise ValueError("PreparedAsset source must not be empty")
        if asset.source in urls:
            raise ValueError(
                f"PreparedAsset source {asset.source!r} was supplied more than once"
            )
        urls[asset.source] = _asset_data_url(asset)
    return urls


def _replace_asset_references(value: str, urls: dict[str, str]) -> str:
    if not urls:
        return value

    def replace_attribute(match: re.Match[str]) -> str:
        raw = match.group("quoted") or match.group("bare") or ""
        replacement = urls.get(unescape(raw))
        if replacement is None:
            return match.group(0)
        quote = match.group("quote") or '"'
        return f"{match.group('prefix')}{quote}{replacement}{quote}"

    def replace_css_url(match: re.Match[str]) -> str:
        raw = (match.group("quoted") or match.group("bare") or "").strip()
        replacement = urls.get(unescape(raw))
        if replacement is None:
            return match.group(0)
        return f'url("{replacement}")'

    return _CSS_URL_RE.sub(
        replace_css_url, _ATTRIBUTE_URL_RE.sub(replace_attribute, value)
    )


def _inject_stylesheets(markup: str, stylesheets: tuple[str, ...]) -> str:
    if not stylesheets:
        return markup
    style_block = "".join(f"<style>{stylesheet}</style>" for stylesheet in stylesheets)
    head_close = _HEAD_CLOSE_RE.search(markup)
    if head_close is None:
        return f"{style_block}{markup}"
    return f"{markup[: head_close.start()]}{style_block}{markup[head_close.start() :]}"


def materialize_prepared_html(prepared: PreparedHtml) -> str:
    """Build one self-contained browser document from a prepared payload."""
    urls = _asset_urls(prepared.assets)
    stylesheets = tuple(
        _replace_asset_references(stylesheet, urls)
        for stylesheet in prepared.stylesheets
    )
    document = (
        _inject_stylesheets(prepared.markup, stylesheets)
        if stylesheets
        else prepared.html
    )
    return _replace_asset_references(document, urls)


__all__ = ["materialize_prepared_html"]
