"""Chat system prompt — user-editable, not baked into code or config.yaml.

Lives at ~/.config/prisma/chat_system_prompt.md as plain text (no YAML
frontmatter — it's a config artifact, not a vault node). Materialized with
the default on first use so the file always exists and is discoverable for
editing, same bootstrap pattern as config.yaml itself.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_CHAT_SYSTEM_PROMPT = """\
You are Prisma, a research assistant with access to the user's personal \
knowledge vault: notes, saved papers, and a knowledge graph of concepts \
extracted from them. Ground your answers in the user's own material when \
it's relevant, and say so explicitly when you're answering from general \
knowledge instead. When you use retrieved content, mention which source \
file it came from.
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


def _prompt_path() -> Path:
    return Path.home() / ".config" / "prisma" / "chat_system_prompt.md"


def _excerpt_summary_prompt_path() -> Path:
    return Path.home() / ".config" / "prisma" / "excerpt_summary_prompt.md"


def load_system_prompt() -> str:
    path = _prompt_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CHAT_SYSTEM_PROMPT, encoding="utf-8")
    return DEFAULT_CHAT_SYSTEM_PROMPT.strip()


def load_excerpt_summary_prompt() -> str:
    path = _excerpt_summary_prompt_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_EXCERPT_SUMMARY_PROMPT, encoding="utf-8")
    return DEFAULT_EXCERPT_SUMMARY_PROMPT.strip()
