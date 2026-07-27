"""Config-section diffing for `POST /reload` (see prisma_cli.py's
`reload-config` command).

Deliberately not a generic recursive diff engine: only 4 PrismaConfig
sections are ever cached in a long-lived server object that needs an
explicit rebuild to pick up a change (see TODO.md's "CLI minimization"
entry for the full investigation of which sections are already read fresh
per-call and need nothing done at all).
"""
from __future__ import annotations

from prisma.utils.config import PrismaConfig


def diff_config_sections(old: PrismaConfig, new: PrismaConfig) -> list[str]:
    """Return the names of sections that changed between two loaded configs.

    Pydantic's BaseModel.__eq__ already does field-wise comparison, so no
    recursive diff machinery is needed here.
    """
    changed: list[str] = []
    if old.vault_root != new.vault_root:
        changed.append("vault_root")
    if old.sources.zotero != new.sources.zotero:
        changed.append("sources.zotero")
    if old.retrieval != new.retrieval:
        changed.append("retrieval")
    if old.chat != new.chat or old.llm.host != new.llm.host:
        changed.append("chat")
    return changed
