from __future__ import annotations

from nonebot_plugin_htmlrender.preparation.references import (
    css_at_rules,
    css_resource_references,
    inspect_html_references,
    rewrite_css_references,
    rewrite_html_references,
)


def _memory_reference(reference: str) -> str | None:
    if reference.startswith("data:"):
        return None
    return f"memory:{reference}"


def test_css_scanner_skips_comments_and_strings_and_rewrites_tokens() -> None:
    css = """
/* url(comment.png) */
.literal::before { content: "url(string.png)"; }
@import "theme.css";
@import url("nested.css");
.image { background: url(icon.png); }
"""

    assert css_resource_references(css) == (
        "theme.css",
        "nested.css",
        "icon.png",
    )

    rewritten = rewrite_css_references(css, _memory_reference)

    assert "url(comment.png)" in rewritten
    assert '"url(string.png)"' in rewritten
    assert '@import "memory:theme.css"' in rewritten
    assert 'url("memory:nested.css")' in rewritten
    assert "url(memory:icon.png)" in rewritten
    assert css_at_rules(css) == ("import", "import")


def test_html_scanner_only_rewrites_real_resource_tokens() -> None:
    html = """<!doctype html>
<!-- <img src="comment.png"> -->
<script>const sample = '<img src="script.png">';</script>
<img src="image.png"
     srcset="data:image/png;base64,AAAA 1x, image@2x.png 2x"
     style="background: url(frame.png)">
<video poster="poster.png"></video>
<svg><use xlink:href="sprite.svg#mark"></use></svg>
<style media="print">/* url(no.png) */ .hero { mask: url(mask.svg) }</style>
"""

    snapshot = inspect_html_references(html, base_url="file:///tmp/document.html")

    assert snapshot.has_script is True
    assert snapshot.references == [
        "image.png",
        "data:image/png;base64,AAAA",
        "image@2x.png",
        "frame.png",
        "poster.png",
        "sprite.svg#mark",
        "mask.svg",
    ]
    assert snapshot.stylesheets[0].media == "print"

    rewritten = rewrite_html_references(html, _memory_reference)

    assert '<img src="comment.png">' in rewritten
    assert "script.png" in rewritten
    assert 'src="memory:image.png"' in rewritten
    assert "data:image/png;base64,AAAA 1x" in rewritten
    assert "memory:image@2x.png 2x" in rewritten
    assert "url(memory:frame.png)" in rewritten
    assert 'poster="memory:poster.png"' in rewritten
    assert 'xlink:href="memory:sprite.svg#mark"' in rewritten
    assert "/* url(no.png) */" in rewritten
    assert "url(memory:mask.svg)" in rewritten


def test_html_scanner_handles_unclosed_and_self_closing_style_tags() -> None:
    snapshot = inspect_html_references(
        '<style/><img src="image.png"><style media="screen">.x{background:url(x.png)}'
    )

    assert snapshot.references == ["image.png", "x.png"]
    assert len(snapshot.stylesheets) == 1
    assert snapshot.stylesheets[0].css == ".x{background:url(x.png)}"
    assert snapshot.stylesheets[0].media == "screen"


def test_token_scanners_ignore_fake_stylesheet_links_and_at_rules() -> None:
    html = """
<!-- <link rel="stylesheet" href="comment.css"> -->
<script>const link = '<link rel="stylesheet" href="script.css">';</script>
<link rel="preload stylesheet" href="real.css">
"""
    css = '/* @import "comment.css" */ .x::before{content:"@font-face"}'

    snapshot = inspect_html_references(html)

    assert snapshot.linked_stylesheets == ["real.css"]
    assert css_at_rules(css) == ()


def test_html_scanner_uses_only_the_first_real_base_href() -> None:
    html = """
<!-- <base href="comment/"> -->
<script>const base = '<base href="script/">';</script>
<base target="_blank"><base href="assets/"><base href="ignored/">
"""

    assert inspect_html_references(html).base_href == "assets/"


def test_srcset_scanner_handles_compact_candidates_and_url_commas() -> None:
    html = (
        '<img srcset="first.png,second.png, '
        'data:image/png;base64,AAAA 2x, image.png?crop=1,2 3x">'
    )

    snapshot = inspect_html_references(html)

    assert snapshot.references == [
        "first.png",
        "second.png",
        "data:image/png;base64,AAAA",
        "image.png?crop=1,2",
    ]

    rewritten = rewrite_html_references(html, _memory_reference)
    assert 'srcset="memory:first.png,memory:second.png,' in rewritten
    assert "data:image/png;base64,AAAA 2x" in rewritten
    assert "memory:image.png?crop=1,2 3x" in rewritten
