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
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from prisma.agents.session_graph import build_session_graph
from prisma.services.chroma_service import ChromaIndexer
from prisma.services.injection_defense import wrap_untrusted
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import Chat

if TYPE_CHECKING:
    import networkx as nx

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
        description=(
            "Semantic search over the vault's ChromaDB embedding index — finds "
            "notes/sources/chats by meaning, not just keyword match. Default "
            "first step for almost any question about the user's notes/papers."
        ),
    ),
    ToolSpec(
        name="graph_context",
        marker="GRAPH_CONTEXT",
        description=(
            "Traverses the Knowledge Graph (KG) — entities and relationships "
            "extracted across the whole vault — to answer questions about how "
            "things connect. Call when the question is about how things relate "
            "to each other, or a vault search alone would likely be "
            "scattered/incomplete."
        ),
    ),
    ToolSpec(
        name="recall",
        marker="RECALL",
        description=(
            "Searches THIS conversation's own history — earlier turns, tool "
            "results, and claims — for something you saw before but that "
            "isn't shown above (older turns roll off as the conversation "
            "grows). Call when you need to remember something specific from "
            "earlier in this same chat, not for new information from the vault."
        ),
    ),
]

TOOL_CALL_RE = re.compile(
    r"^(" + "|".join(re.escape(t.marker) for t in TOOLS) + r"):\s*(.+)$",
    re.MULTILINE,
)

# ADR-017 claim attribution. Same pattern-based convention as tool calls
# (ADR-014's appendix found free-text markers more reliable than native
# function-calling on today's local model) -- a single trailing line rather
# than a new per-line marker, since footnote data is naturally a list, not
# a single value. Only the *last* match is used (ChatAgent.respond) in case
# the model discusses the format itself earlier in its answer.
FOOTNOTES_LINE_RE = re.compile(r"^FOOTNOTES_JSON:\s*(.+)$", re.MULTILINE)


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


def system_prompt_footnote_section() -> str:
    """ADR-017: mark, per claim, whether it's traceable to a specific vault
    document or is the model's own inference -- mirroring academic citation
    practice. See docs/concepts/footnote.md for the full field reference;
    this is the operational instruction, not the design rationale."""
    return "\n".join([
        "For every substantive claim in your answer (not filler like "
        '"Sure, here\'s what I found"), mark where it came from, so the '
        "reader can tell what traces to a document vs. what is your own "
        "reasoning:",
        "",
        "- Right after a claim that traces to a document, write an inline "
        "marker in this exact format: [^N] where N is the next unused "
        "number, starting at 1 (e.g. \"...uses self-attention[^1].\"). Do "
        "this whether it's a direct quote, a paraphrase of one document, "
        "or a claim that connects/synthesizes two or more documents.",
        "- Right after a claim that is your own reasoning, generalization, "
        "or general knowledge -- NOT traceable to any specific document "
        "you were given -- also mark it with the next [^N], but it will "
        "get relation \"ai-inference\" below. You do not need to mark "
        "filler or purely conversational sentences, only actual claims.",
        "- Place each [^N] immediately next to the exact sentence or span "
        "it supports, at the point in your answer where you make that "
        "claim -- NOT gathered together at the end. A citation marker is "
        "tied to precisely that text, so \"...uses self-attention[^1], "
        "and normalizes with RMSNorm[^2].\" is correct; writing the full "
        "sentence with no markers and then appending \"[^1][^2]\" "
        "afterward is wrong, even though it looks similar. If your "
        "answer makes three separate claims, it should have three "
        "markers at three different places in the text, not clustered "
        "in one spot.",
        "- Only cite documents you actually saw in a tool result in this "
        "conversation (their exact slug, shown as the `path=` of an "
        "<untrusted_source> block, or in a GRAPH_CONTEXT tool result's "
        "\"Sources:\" line). Never invent a slug.",
        "",
        "After your answer, on its own final line, list every [^N] marker "
        "you used as a single-line JSON array, exactly in this format:",
        "",
        'FOOTNOTES_JSON: [{"index": 1, "relation": "citation", '
        '"sources": ["slug-a"]}, {"index": 2, "relation": "relational", '
        '"sources": ["slug-b", "slug-c"]}, {"index": 3, '
        '"relation": "ai-inference", "sources": []}]',
        "",
        "relation is one of:",
        "- citation — direct quote or close paraphrase, exactly one source",
        "- attribution — paraphrased/synthesized from one source, exactly "
        "one source",
        "- relational — connects or synthesizes across sources, two or "
        "more sources (this is what a GRAPH_CONTEXT result usually is)",
        "- ai-inference — your own reasoning, no document behind it, "
        "sources must be an empty list",
        "",
        "If you added no [^N] markers at all, still write "
        '"FOOTNOTES_JSON: []" as the last line -- do not omit it.',
    ])


class ChatToolbox:
    """Dispatches a detected tool marker to its implementation. Holds the
    already-constructed service instances (same ones app.py's other
    endpoints use) rather than constructing its own."""

    def __init__(self, chroma: ChromaIndexer, kg: KnowledgeGraphClient, vault: VaultService) -> None:
        self._chroma = chroma
        self._kg = kg
        self._vault = vault

    def call(
        self, marker: str, query: str, *,
        session_graph: "nx.MultiDiGraph | None" = None, remaining_budget: int = 4000,
        chat_slug: str | None = None,
    ) -> ToolResult:
        if marker == "SEARCH_VAULT":
            return self._search_vault(query)
        if marker == "GRAPH_CONTEXT":
            return self._graph_context(query)
        if marker == "RECALL":
            return self._recall(query, session_graph, remaining_budget, chat_slug)
        raise ValueError(f"unknown tool marker: {marker!r}")

    def get_node_text(self, slug: str) -> str | None:
        """Resolves a footnote's `sources` slug back to plain text, for
        ADR-017's faithfulness_checked verification (ChatAgent._verify_footnote).
        Covers the same node types footnotes/wiki-links can point to --
        Note/Source's `body`, or a Chat's full message transcript joined.
        Returns None on a missing/unresolvable slug rather than raising, so
        one stale or hallucinated slug doesn't break verification for the
        other footnotes in the same turn."""
        try:
            node = self._vault.get_any(slug)
        except FileNotFoundError:
            return None
        if isinstance(node, Chat):
            return "\n\n".join(m.content.value for m in node.messages) or None
        return getattr(node, "body", None) or None

    def _search_vault(self, query: str, top_k: int = 5) -> ToolResult:
        hits = self._chroma.query(query, top_k=top_k)
        items = []
        for h in hits:
            path = self._vault.root / h.source_file
            try:
                excerpt = path.read_text(encoding="utf-8", errors="replace")[:_EXCERPT_CHARS]
            except OSError:
                excerpt = ""
            items.append({"source_file": h.source_file, "score": h.score, "text": excerpt})
        # Wrapped under the vault slug (not the raw source_file path) --
        # this is exactly the identifier a footnote's `sources` list
        # expects (ADR-017), so the model can copy it verbatim rather than
        # having to derive a slug from a path itself.
        wrapped = "\n\n".join(
            wrap_untrusted(Path(i["source_file"]).stem, i["text"]) for i in items if i["text"]
        )
        return ToolResult(text=wrapped, raw=items)

    def _graph_context(self, query: str, budget: int = 1500) -> ToolResult:
        results = self._kg.query(query, budget=budget)
        text = results[0].text if results else ""
        sources = results[0].sources if results else []
        if text:
            # `relational` footnotes need 2+ sources (see FootnoteRelation
            # docs) -- listing them explicitly, not just relying on the
            # slugs already mentioned in `text`'s prose lines, gives the
            # model an unambiguous list to copy into FOOTNOTES_JSON.
            header = f"Sources: {', '.join(sources)}\n\n" if sources else ""
            wrapped = wrap_untrusted("knowledge-graph", header + text)
        else:
            wrapped = ""
        return ToolResult(text=wrapped, raw=[r.model_dump() for r in results])

    # ── RECALL (ADR-019, docs/concepts/chat-session-graph.md) ───────────────

    def _recall(
        self, query: str, session_graph: "nx.MultiDiGraph | None", remaining_budget: int,
        chat_slug: str | None = None,
    ) -> ToolResult:
        """Searches the whole session graph (not just tool-call/thinking
        branches -- `_bounded_history()`/`SessionOrchestrator.bounded_history()`
        already drop whole rolled-off turns, which `RECALL` must be able to
        reach too), ranked by embedding similarity to `query` when the
        embedding lease is granted, degrading to recency order otherwise --
        never silently returning nothing just because the shared local
        compute is busy.

        `chat_slug` (the active chat's own slug) additionally pulls in the
        `_RECALL_CROSS_CHAT_LIMIT` most-recently-modified *other* chats'
        graphs -- cservinl's reasoning: recalling every chat in the vault
        gets more expensive (a full graph rebuild + embed pass per chat)
        with no bound as the vault grows, and the most recently active other
        chats are the ones most likely to actually be relevant to what's
        being discussed right now, so that's the cheap, well-justified place
        to cut rather than an arbitrary cap. Cross-chat candidates are
        scored with `_RECALL_CROSS_CHAT_DISCOUNT` applied -- "a lower grade
        of attention" -- so an in-chat match wins unless a cross-chat one is
        substantially more relevant. None if `chat_slug` isn't given (tests,
        or any caller that doesn't have an active chat to exclude), matching
        the original single-chat-only behavior exactly."""
        candidates: list[tuple[str, str, str, str | None]] = []
        if session_graph is not None:
            candidates += [
                (node_id, attrs["kind"], text, None)
                for node_id, attrs in session_graph.nodes(data=True)
                if (text := _recall_node_text(attrs["kind"], attrs["data"]))
            ]
        cross_chat: list[tuple[str, str, str, str | None]] = []
        if chat_slug is not None:
            for other in _recent_other_chats(self._vault, exclude_slug=chat_slug, limit=_RECALL_CROSS_CHAT_LIMIT):
                other_graph = build_session_graph(other.messages)
                cross_chat += [
                    (node_id, attrs["kind"], text, other.slug)
                    for node_id, attrs in other_graph.nodes(data=True)
                    if (text := _recall_node_text(attrs["kind"], attrs["data"]))
                ]
        all_candidates = candidates + cross_chat
        if not all_candidates:
            return ToolResult(text="(nothing to recall yet)", raw=[])

        vectors = self._chroma.embed_texts(
            [query] + [text for _, _, text, _ in all_candidates],
            priority="interactive", max_wait=_RECALL_LEASE_MAX_WAIT,
        )
        if vectors is not None:
            query_vec, candidate_vecs = vectors[0], vectors[1:]

            def _score(candidate: tuple[str, str, str, str | None], vec: list[float]) -> float:
                base = _cosine(query_vec, vec)
                return base if candidate[3] is None else base * _RECALL_CROSS_CHAT_DISCOUNT

            ranked = [
                c for c, _ in sorted(zip(all_candidates, candidate_vecs), key=lambda cv: -_score(cv[0], cv[1]))
            ]
        else:
            # Lease denied or the embed call itself failed -- degrade to
            # recency, don't wait or fail the turn. networkx preserves node
            # insertion order; build_session_graph() adds nodes in
            # chat.messages order, so reversed() is newest-first. Cross-chat
            # candidates are dropped in this path rather than guessed at --
            # without embeddings there's no principled way to interleave
            # cross-chat recency against a discount weight.
            ranked = list(reversed(candidates))

        packed = _pack_within_budget(ranked, remaining_budget)
        if not packed:
            return ToolResult(text="(nothing found)", raw=[])
        text = "\n\n".join(
            wrap_untrusted(
                f"recalled-{kind}" if slug is None else f"recalled-{kind}-from-chat-{slug}", t,
            )
            for _, kind, t, slug in packed
        )
        return ToolResult(text=text, raw=[
            {"node_id": nid, "kind": kind, "chat_slug": slug} for nid, kind, _, slug in packed
        ])


_RECALL_LEASE_MAX_WAIT = 0.5  # fail fast on contention -- a live turn is waiting, unlike background indexing
_RECALL_CROSS_CHAT_LIMIT = 8  # cap: only the N most-recently-modified OTHER chats get graph-rebuilt + embedded per RECALL call
_RECALL_CROSS_CHAT_DISCOUNT = 0.7  # "a lower grade of attention" -- an in-chat match wins unless a cross-chat one is substantially more relevant


def _recent_other_chats(vault: VaultService, *, exclude_slug: str, limit: int) -> list[Chat]:
    # `list_chats()` fully parses every `.sess` file in the vault just to
    # read `modified_at` off each -- the cap below only bounds the expensive
    # part (graph rebuild + embedding per chat), not this listing step
    # itself. Fine at today's vault-chat-count scale; if this listing ever
    # shows up as real per-turn latency, the fix is a lightweight
    # slug+modified_at-only listing, not a smaller cap.
    others = [c for c in vault.list_chats() if c.slug != exclude_slug]
    others.sort(key=lambda c: c.modified_at, reverse=True)
    return others[:limit]


def _recall_node_text(kind: str, data) -> str:
    if kind == "turn":
        return data.content.value
    if kind == "tool_call":
        return data.result or ""
    if kind == "thought":
        return data.thought
    if kind == "claim":
        return data.claim_text
    return ""


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


def _pack_within_budget(
    ranked: list[tuple[str, str, str, str | None]], remaining_budget: int,
) -> list[tuple[str, str, str, str | None]]:
    """Greedily packs ranked candidates until the budget is used up --
    proactively self-limiting, not relying on ChatAgent's post-hoc context-
    overflow check to fail the whole turn if RECALL returned too much."""
    packed: list[tuple[str, str, str, str | None]] = []
    used = 0
    for candidate in ranked:
        cost = len(candidate[2]) // 4
        if used + cost > remaining_budget:
            continue  # doesn't fit -- a smaller, lower-ranked candidate still might
        packed.append(candidate)
        used += cost
    return packed
