"""SessionOrchestrator -- per-turn context assembly for chat sessions (ADR-019,
docs/concepts/chat-session-graph.md). Two responsibilities, kept separate from
ChatAgent's tool-calling loop mechanics:

1. Cheap algorithmic default assembly (no LLM call) -- system prompt + tool
   section + Excerpt + a token-budget-bounded walk of the main line. Same
   algorithm `ChatAgent._full_system_prompt()`/`_bounded_history()` used
   before this class existed, relocated here, not rewritten.
2. A lazy, per-call in-memory session graph (`networkx.MultiDiGraph`), used
   by the `RECALL` tool (`chat_tools.py`) to search beyond what the default
   assembly includes -- rebuilt fresh from a chat's own messages each call,
   deliberately not persisted or cached across calls (see the concept doc's
   engine-choice section for why this is intentionally not a database: a
   session's own node count is small enough that rebuilding is cheap, and
   skipping persistence sidesteps any staleness-vs-`.sess` drift entirely).
"""
from __future__ import annotations

import networkx as nx

from prisma.agents.session_graph import build_session_graph
from prisma.services.chat_tools import system_prompt_footnote_section, system_prompt_tool_section
from prisma.storage.models.vault_models import Note, TurnNode


def _estimate_tokens(text: str) -> int:
    return len(text) // 4  # same rough char/4 heuristic used throughout this codebase


class SessionOrchestrator:
    def __init__(self, system_prompt: str, max_history_tokens: int) -> None:
        self._system_prompt = system_prompt
        self._max_history_tokens = max_history_tokens

    @property
    def max_history_tokens(self) -> int:
        return self._max_history_tokens

    def full_system_prompt(self, excerpt_notes: list[Note]) -> str:
        parts = [self._system_prompt, system_prompt_tool_section(), system_prompt_footnote_section()]
        if excerpt_notes:
            parts.append(self._excerpt_context_block(excerpt_notes))
        return "\n\n".join(parts)

    def _excerpt_context_block(self, excerpt_notes: list[Note]) -> str:
        # Deliberately NOT subject to bounded_history's rolling truncation --
        # this is durable, user-curated ground truth for this conversation,
        # so it must survive even after the turns that produced it roll away.
        lines = [
            "Already established in this conversation (curated by the user "
            "— treat as settled, don't re-litigate or re-ask about these):",
        ]
        for note in excerpt_notes:
            lines.append(f"\n### {note.title}\n{note.body}")
        return "\n".join(lines)

    def bounded_history(self, history: list[TurnNode]) -> list[TurnNode]:
        """Keep the most recent turns whose combined estimated token count
        fits max_history_tokens, dropping the oldest first. Turns dropped
        here aren't lost -- they stay in the `.sess` file and are reachable
        via `RECALL` (chat_tools.py), which searches the whole session graph
        this class also builds, not just what this method keeps."""
        kept: list[TurnNode] = []
        used = 0
        for m in reversed(history):
            cost = _estimate_tokens(m.content.value)
            if used + cost > self._max_history_tokens:
                break
            kept.append(m)
            used += cost
        kept.reverse()
        return kept

    def graph_for(self, messages: list[TurnNode]) -> nx.MultiDiGraph:
        """Delegates to session_graph.build_session_graph() -- kept as a
        method here for existing call sites (`ChatAgent.respond()`) since a
        chat's own graph is squarely this class's concern; the standalone
        function exists so chat_tools.py's cross-chat RECALL can build a
        graph for a chat that ISN'T the active one without this class's
        involvement (and without a circular import back into chat_tools.py,
        which this class already imports from for the system-prompt
        helpers)."""
        return build_session_graph(messages)
