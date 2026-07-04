"""Chat tool registry — pattern-based, not native function-calling.

ADR-014's appendix documents why: an empirical comparison on the actual
local chat model (qwen2.5:7b) showed native Ollama tool-calling picking the
wrong tool and over-triggering, while a hand-written text-pattern
convention was reliably correct. Each tool is invoked by the model writing
a line like `SEARCH_VAULT: <query>`; ChatAgent's loop detects that pattern,
calls the matching function here, and feeds the (sanitized) result back.

Only search_vault and graph_context are implemented for this first
increment — TODO.md's design also sketches expand_node, get_full_text,
god_nodes, surprising_connections, suggest_questions, deferred for later.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from prisma.services.chroma_service import ChromaIndexer
from prisma.services.injection_defense import wrap_untrusted
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.services.vault import VaultService

_EXCERPT_CHARS = 800


class ToolResult(BaseModel):
    # `text` is what goes back into the model's context (already sanitized/
    # wrapped as untrusted content). `raw` is the structured data the UI can
    # render directly (source files, scores) without re-parsing prose.
    text: str
    raw: list[dict] = []


class ToolSpec(BaseModel):
    name: str
    marker: str
    description: str


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_vault",
        marker="SEARCH_VAULT",
        description="Default first step for almost any question about the user's notes/papers.",
    ),
    ToolSpec(
        name="graph_context",
        marker="GRAPH_CONTEXT",
        description=(
            "Call when the question is about how things relate to each other, "
            "or a vault search alone would likely be scattered/incomplete."
        ),
    ),
]

TOOL_CALL_RE = re.compile(
    r"^(" + "|".join(re.escape(t.marker) for t in TOOLS) + r"):\s*(.+)$",
    re.MULTILINE,
)


def system_prompt_tool_section() -> str:
    lines = [
        "You have tools you may call by writing a line in exactly this "
        "format, and nothing else on that line:",
    ]
    for t in TOOLS:
        lines.append(f"{t.marker}: <query text>")
    lines.append("")
    for t in TOOLS:
        lines.append(f"- {t.marker} — {t.description}")
    lines.append(
        "\nIf no tool is needed (e.g. the user is just chatting, or asking "
        "something you can answer directly), just answer normally without "
        "any tool line."
    )
    return "\n".join(lines)


class ChatToolbox:
    """Dispatches a detected tool marker to its implementation. Holds the
    already-constructed service instances (same ones app.py's other
    endpoints use) rather than constructing its own."""

    def __init__(self, chroma: ChromaIndexer, kg: KnowledgeGraphClient, vault: VaultService) -> None:
        self._chroma = chroma
        self._kg = kg
        self._vault = vault

    def call(self, marker: str, query: str) -> ToolResult:
        if marker == "SEARCH_VAULT":
            return self._search_vault(query)
        if marker == "GRAPH_CONTEXT":
            return self._graph_context(query)
        raise ValueError(f"unknown tool marker: {marker!r}")

    def _search_vault(self, query: str, top_k: int = 5) -> ToolResult:
        hits = self._chroma.query(query, top_k=top_k)
        items = []
        for h in hits:
            path = self._vault.root / h["source_file"]
            try:
                excerpt = path.read_text(encoding="utf-8", errors="replace")[:_EXCERPT_CHARS]
            except OSError:
                excerpt = ""
            items.append({"source_file": h["source_file"], "score": h["score"], "text": excerpt})
        wrapped = "\n\n".join(
            wrap_untrusted(i["source_file"], i["text"]) for i in items if i["text"]
        )
        return ToolResult(text=wrapped, raw=items)

    def _graph_context(self, query: str, budget: int = 1500) -> ToolResult:
        results = self._kg.query(query, budget=budget)
        text = results[0]["text"] if results else ""
        wrapped = wrap_untrusted("knowledge-graph", text) if text else ""
        return ToolResult(text=wrapped, raw=results)
