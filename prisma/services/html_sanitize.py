"""Allowlist HTML sanitizer for markdown-rendered content.

Python-Markdown (used by docu_craft's MdHtmlTransformer, see renderer.py)
does not sanitize embedded raw HTML by design -- its own docs: `safe_mode`
was removed years ago for not being reliably safe against untrusted input.
Every caller of `renderer.render()` gets its output routed through this
before `{@html}` ever sees it in the UI, whether the source is
trusted-authorship (a Note/Source, the user's own writing) or semi-trusted
(a chat reply, which can echo tool-result/ingested-document text -- see
ADR-017's 2026-08-04 rendering addendum).

nh3 is a maintained Rust binding of Mozilla's html5ever/ammonia -- not
`bleach`, which has had long stretches of maintenance gaps historically.
"""
from __future__ import annotations

import nh3

_ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "u", "s", "del", "ins",
    "blockquote", "ul", "ol", "li",
    "code", "pre", "span", "div",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img",
}

# "*" attributes apply to every allowed tag, on top of any tag-specific set
# below -- id/class cover docu_craft's own wikilink/citation/transclusion
# wrapper spans and the attr_list/toc extensions' generated anchors, without
# needing to enumerate every tag they might land on.
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "data-citekey"},
    "img": {"src", "alt", "title"},
    "div": {"data-slug"},
    # data-footnote-index: chat replies only (see chat_render.py) -- the
    # click-to-jump/color-by-relation hook the UI attaches to each
    # <span class="footnote-marker"> after {@html} mounts it.
    "span": {"data-footnote-index"},
    "*": {"id", "class"},
}

# No "javascript"/"data" -- a fragment link (docu_craft's own
# #note:slug/#source:slug convention) or a relative/no-scheme URL is
# untouched regardless of this allowlist; it only gates URLs that actually
# specify a scheme (confirmed live: nh3 strips the whole href attribute,
# not just the scheme, for a disallowed one -- the link text survives,
# just not the navigation).
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(html: str) -> str:
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
