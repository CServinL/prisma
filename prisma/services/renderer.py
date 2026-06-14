from __future__ import annotations

import re

import docu_craft.renderers  # registers all format transformers on the workflow graph
from docu_craft.themes import ThemeManager
from docu_craft.workflow import graph as _workflow

from prisma.services.vault import VaultService

# Load once at import time — avoids yaml._yaml C-extension crash on repeated calls
_THEME = ThemeManager.load("prisma")

_TRANSCLUSION_RE = re.compile(r"!\[\[([^\]#]+?)(?:#([^\]]+))?\]\]")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]#]+?)(?:#([^\]]+))?\]\]")
_CITATION_RE = re.compile(r"\[\[@([^\]]+?)\]\]")
_CITEKEY_INDEX: dict[str, str] | None = None

MAX_TRANSCLUSION_DEPTH = 5


def _build_citekey_index(vault: VaultService) -> dict[str, str]:
    from prisma.services.vault import _parse_frontmatter
    index: dict[str, str] = {}
    for path in vault._all_md_files():
        body = path.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(body)
        citekey = fm.get("citekey")
        if citekey:
            index[citekey] = path.stem
    return index


def _resolve_transclusions(body: str, vault: VaultService, depth: int = 0) -> tuple[str, list[str]]:
    broken: list[str] = []
    if depth >= MAX_TRANSCLUSION_DEPTH:
        return body, broken

    def replace(m: re.Match) -> str:
        slug, section = m.group(1).strip(), m.group(2)
        content = vault.body_of(slug)
        if content is None:
            broken.append(slug)
            return f'<span class="broken-transclusion">⚠ ![[{slug}]] not found</span>'
        if section:
            content = _extract_section(content, section) or content
        resolved, child_broken = _resolve_transclusions(content, vault, depth + 1)
        broken.extend(child_broken)
        return f'\n\n<div class="transclusion" data-slug="{slug}">\n\n{resolved}\n\n</div>\n\n'

    return _TRANSCLUSION_RE.sub(replace, body), broken


def _extract_section(body: str, heading: str) -> str | None:
    lines = body.splitlines()
    in_section = False
    level = 0
    result: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            if in_section and len(m.group(1)) <= level:
                break
            if not in_section and m.group(2).strip().lower() == heading.strip().lower():
                in_section = True
                level = len(m.group(1))
        if in_section:
            result.append(line)
    return "\n".join(result) if result else None


def _resolve_wikilinks(body: str, vault: VaultService) -> tuple[str, list[str]]:
    broken: list[str] = []

    def replace(m: re.Match) -> str:
        slug, section = m.group(1).strip(), m.group(2)
        anchor = f"#{section}" if section else ""
        if vault.slug_exists(slug):
            return f'<a class="wikilink" href="#note:{slug}{anchor}">{slug}</a>'
        broken.append(slug)
        return f'<span class="broken-wikilink">⚠ [[{slug}]]</span>'

    return _WIKILINK_RE.sub(replace, body), broken


def _resolve_citations(body: str, citekey_index: dict[str, str]) -> tuple[str, list[str]]:
    broken: list[str] = []

    def replace(m: re.Match) -> str:
        citekey = m.group(1).strip()
        slug = citekey_index.get(citekey)
        if slug:
            return f'<a class="citation" href="#source:{slug}" data-citekey="{citekey}">@{citekey}</a>'
        broken.append(citekey)
        return f'<span class="broken-citation">⚠ @{citekey}</span>'

    return _CITATION_RE.sub(replace, body), broken


def render(markdown: str, vault: VaultService) -> tuple[str, list[str], list[str]]:
    """
    Resolve DSL notation, then convert md → HTML via docu-craft prisma theme.
    Returns (html, broken_links, broken_citations).
    """
    citekey_index = _build_citekey_index(vault)

    body, broken_transclusions = _resolve_transclusions(markdown, vault)
    body, broken_wikilinks = _resolve_wikilinks(body, vault)
    body, broken_citations = _resolve_citations(body, citekey_index)

    broken_links = broken_transclusions + broken_wikilinks

    full_html = _workflow.run(body, from_fmt="md", to_fmt="html", css=_THEME.css, style=_THEME.style)

    # docu-craft returns a full document — extract only the body fragment so
    # injecting via {@html} doesn't create a nested <html> in the DOM.
    m = re.search(r"<body[^>]*>(.*?)</body>", full_html, re.DOTALL)
    html = m.group(1).strip() if m else full_html

    return html, broken_links, broken_citations
