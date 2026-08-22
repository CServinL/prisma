"""Chat system prompt — fixed in source, not persisted to disk.

Split into two layers:

- CHAT_SYSTEM_PROMPT (below): the base prompt, a plain code constant. Always
  reflects whatever's in the current release -- there is deliberately no
  on-disk copy of this to go stale. The old design wrote this to
  ~/.config/prisma/chat_system_prompt.md the first time it materialized and
  read only that file forever after; a deployment that had already
  materialized the file before some later improvement to this constant would
  never see that improvement, silently, with nothing to signal the drift.
  Confirmed live on 2026-08-22: the deployed file was still whatever this
  constant said on 2026-07-25, untouched by several code releases since.
- The user prompt (chat_user_prompt.md, load_user_prompt/save_user_prompt
  below): genuinely user-owned, blank by default, layered on top by
  build_system_prompt(). A user's customization here can never shadow a
  future improvement to CHAT_SYSTEM_PROMPT, because it's additive, not a
  full replacement.
"""
from __future__ import annotations

from pathlib import Path

CHAT_SYSTEM_PROMPT = """\
You are Prisma, a research assistant with access to the user's personal \
knowledge vault: notes, saved papers, and a knowledge graph of concepts \
extracted from them, all searchable through a semantic index (ChromaDB) \
and the knowledge graph. This includes past chat transcripts, not just \
notes and sources -- you may pull in relevant information from earlier \
conversations the same way you would from any other vault content. Ground \
your answers in the user's own material when it's relevant. When you \
use retrieved content, mention which source file it came from.
"""

# Used by compressed-mode Excerpt regeneration (ADR-015): condenses the
# currently pinned chat turns into a single durable summary each time the
# pinned set changes, so the model's live context can stop carrying the raw
# turns once they're folded in here.
DEFAULT_EXCERPT_SUMMARY_PROMPT = """\
Summarize the following pinned chat turns into a single, condensed excerpt.

Keep:
- Core concepts and definitions discussed
- Rationale behind decisions and recommendations
- Findings, conclusions, and takeaways
- Questions raised and their answers, stated conceptually

Strip:
- Illustrative examples, analogies, or worked examples used only to explain \
a concept
- Code snippets, diagrams, or other non-prose content
- Small talk and back-and-forth clarification that carries no lasting \
information

Write it as a coherent, condensed narrative, not a list of per-turn \
summaries — a reader should be able to pick up the conversation's \
conclusions from this alone, without needing the raw turns.
"""


def _user_prompt_path() -> Path:
    return Path.home() / ".config" / "prisma" / "chat_user_prompt.md"


def _excerpt_summary_prompt_path() -> Path:
    return Path.home() / ".config" / "prisma" / "excerpt_summary_prompt.md"


def load_user_prompt() -> str:
    """Blank by default -- unlike the old chat_system_prompt.md, nothing is
    ever auto-materialized here. An unwritten file and an empty save() both
    mean "no standing user instructions," so there's nothing worth putting
    on disk until the user actually saves something."""
    path = _user_prompt_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def save_user_prompt(content: str) -> None:
    """User-facing edit path (Settings page's "Chat instructions" panel) --
    caller is still responsible for calling POST /reload/chat afterwards so
    the running ChatAgent picks it up, same as any manual edit of this file
    always required."""
    path = _user_prompt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stripped = content.strip()
    path.write_text(stripped + "\n" if stripped else "", encoding="utf-8")


def build_system_prompt() -> str:
    """CHAT_SYSTEM_PROMPT (fixed, code-owned) plus the user's own additive
    instructions layered on top, if any -- see this module's docstring for
    why these are two separate layers rather than one editable file."""
    base = CHAT_SYSTEM_PROMPT.strip()
    user = load_user_prompt()
    if not user:
        return base
    return f"{base}\n\nThe user has also added these standing instructions -- follow them too:\n{user}"


def load_excerpt_summary_prompt() -> str:
    path = _excerpt_summary_prompt_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_EXCERPT_SUMMARY_PROMPT, encoding="utf-8")
    return DEFAULT_EXCERPT_SUMMARY_PROMPT.strip()
