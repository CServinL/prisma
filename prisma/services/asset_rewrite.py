"""Rewrites relative asset references (src/href/srcset/CSS url()/etc.) in
vault-served HTML to absolute /vault/assets/... URLs, so the browser can
fetch them regardless of which route rendered the HTML. Pure string
transforms, no FastAPI Request dependency, so it's unit-testable without
spinning up routes.

Previously duplicated three times in prisma/server/app.py (get_note's two
.html branches, view_html), each independently recomputing the same
prefix and covering a different subset of attributes -- only view_html
handled srcset, CSS url(), JSON string literals, and the WebKitGTK
xlink:href fixup. Consolidated here; each caller picks the `mode` that
matches what it renders.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Match

_ABS = r'(?:https?|data|javascript|mailto|tel):|//'
_SKIP = rf'(?!\s*(?:{_ABS}|#|/))'
_ASSET_EXT = r'\.(?:png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf|eot|css|js|map)'


def asset_prefix(vault_root: Path, file_path: Path, base_url: str) -> str:
    """Absolute URL prefix for assets that sit alongside *file_path* in the
    vault, e.g. "http://host:port/vault/assets/sub/dir/". Falls back to the
    vault-root prefix if *file_path* isn't actually under *vault_root*."""
    try:
        rel_dir = file_path.parent.relative_to(vault_root)
        base = "" if rel_dir == Path(".") else str(rel_dir).replace("\\", "/").rstrip("/")
    except ValueError:
        base = ""
    return f"{base_url}vault/assets/{base}/" if base else f"{base_url}vault/assets/"


def _rewrite_value(val: str, prefix: str) -> str:
    if re.match(rf'\s*(?:{_ABS}|#|/)', val):
        return val
    return prefix + val


def rewrite_html(html: str, prefix: str, *, mode: Literal["full", "fragment", "markdown"] = "full") -> str:
    """Rewrite relative asset references in *html* to absolute URLs under
    *prefix*. `mode` picks how much rewriting is applied:

    - "markdown": markdown rendered via vault_render() -- only <img src>
      (or similar) ever appears with a relative, asset-extension value;
      everything else vault_render already emits fully-qualified.
    - "fragment": an extracted <body>/<style> fragment from a companion
      .html node -- src/href, no extension filter.
    - "full" (default): a complete standalone .html document served to an
      iframe -- src/href/action/poster/data, srcset, CSS url(), JSON
      string literals, and the WebKitGTK xlink:href="data:..." fixup.
    """
    if mode == "markdown":
        return re.sub(
            rf'(?<![:\w])(src)="{_SKIP}([^"]+{_ASSET_EXT})"',
            lambda mo: f'{mo.group(1)}="{prefix}{mo.group(2)}"',
            html,
        )

    if mode == "fragment":
        return re.sub(
            rf'(?<![:\w])(src|href)="{_SKIP}([^"]*)"',
            lambda mo: f'{mo.group(1)}="{prefix}{mo.group(2)}"',
            html,
        )

    # mode == "full"
    html = re.sub(r'xlink:href="(data:[^"]*)"', r'href="\1"', html)

    html = re.sub(
        rf'(?<![:\w])(src|href|action|poster|data)="{_SKIP}([^"]*)"',
        lambda m: f'{m.group(1)}="{_rewrite_value(m.group(2), prefix)}"',
        html,
    )

    def _rewrite_srcset(m: Match) -> str:
        parts = []
        for entry in m.group(1).split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split()
            tokens[0] = _rewrite_value(tokens[0], prefix)
            parts.append(" ".join(tokens))
        return f'srcset="{", ".join(parts)}"'
    html = re.sub(r'srcset="([^"]*)"', _rewrite_srcset, html)

    html = re.sub(
        rf"""url\(\s*(['"]?){_SKIP}([^'"\)]+)\1\s*\)""",
        lambda m: f'url({m.group(1)}{_rewrite_value(m.group(2), prefix)}{m.group(1)})',
        html,
    )

    html = re.sub(
        rf'"({_SKIP}[^"]+\.(?:png|jpg|jpeg|gif|webp|svg|woff2?|ttf|eot|css|js))"',
        lambda m: f'"{_rewrite_value(m.group(1), prefix)}"',
        html,
    )
    return html
