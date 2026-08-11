from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from prisma.schema_gov import RichContent, VersionedModel


def _new_id() -> str:
    return uuid4().hex


class NodeType(str, Enum):
    note = "note"
    source = "source"
    chat = "chat"
    stream = "stream"


class StreamStatus(str, Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class RefreshFrequency(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    manual = "manual"


class SourceKind(str, Enum):
    paper = "paper"
    document = "document"
    web = "web"
    media = "media"


class SourceOrigin(str, Enum):
    zotero = "zotero"
    upload = "upload"
    url = "url"


class NoteStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"


# ── Base ──────────────────────────────────────────────────────────────────────

class VaultNodeBase(BaseModel):
    slug: str
    title: str
    node_type: NodeType
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    modified_at: datetime = Field(default_factory=datetime.utcnow)
    path: Path

    @field_validator("slug")
    @classmethod
    def slug_url_safe(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_\.]*$", v):
            raise ValueError(f"slug contains invalid URL characters: {v!r}")
        return v


# ── Vault node types ──────────────────────────────────────────────────────────

class Note(VaultNodeBase):
    node_type: NodeType = NodeType.note
    body: str = ""
    status: NoteStatus = NoteStatus.active
    excerpt_of_chat: str | None = None
    original_ext: str | None = None


class Source(VaultNodeBase):
    node_type: Literal[NodeType.source] = NodeType.source
    source_kind: SourceKind = SourceKind.paper
    origin: SourceOrigin = SourceOrigin.zotero
    citekey: str
    zotero_key: str | None = None
    stream_id: str | None = None
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    body: str = ""
    # Extension of the companion original file, e.g. ".pdf", ".html", ".svg".
    # Companion lives at <Zotero Imported dir>/<slug><original_ext>. None when only .md exists.
    original_ext: str | None = None


CHAT_SCHEMA_VERSION = 2


class ToolCallNode(BaseModel):
    """One tool invocation, off the main line (`TurnNode.tool_calls`) --
    unlike v1's `ToolCallRecord`, `result` is persisted, not discarded, so a
    later turn can `RECALL` it instead of only ever re-running the tool."""
    id: str = Field(default_factory=_new_id)
    tool: str
    args: dict = Field(default_factory=dict)
    result: str | None = None
    status: Literal["ok", "error"] = "ok"


class ThinkingNode(BaseModel):
    """One reasoning step, off the main line (`TurnNode.thoughts`) -- the
    sequentialthinking-motivated shape (see ADR-019/chat-session-graph.md).
    Schema support only; nothing populates this yet (gated behind the
    still-deferred model-category `has_native_reasoning` flag)."""
    id: str = Field(default_factory=_new_id)
    thought: str
    thought_number: int
    revises: str | None = None  # another ThinkingNode.id this one revises
    branches_from: str | None = None  # another ThinkingNode.id this one forks from


class CitedClaimNode(BaseModel):
    """A claim traceable to specific vault document(s) -- `citation`/
    `attribution`/`relational` share this shape (all have real `sources`, a
    meaningful `faithfulness_checked`), unlike `InferenceNode` below, which
    structurally has neither. See docs/ontologia.md Axiom 16."""
    id: str = Field(default_factory=_new_id)
    kind: Literal["claim"] = "claim"
    index: int  # sequential per turn, 1-based -- the inline [^N] marker this claim is
    claim_text: str
    sources: list[str] = Field(default_factory=list)  # Note/Source/Chat slugs
    relation: Literal["citation", "attribution", "relational"]
    # Whether an automated/manual check confirmed the claim accurately
    # represents `sources`. None = not (yet) checked.
    faithfulness_checked: bool | None = None


class InferenceNode(BaseModel):
    """A claim that's the model's own reasoning, traceable to no specific
    vault document -- structurally distinct from CitedClaimNode (no
    `sources`, nothing for `faithfulness_checked` to check), not the same
    shape with empty fields."""
    id: str = Field(default_factory=_new_id)
    kind: Literal["inference"] = "inference"
    index: int  # sequential per turn, 1-based -- the inline [^N] marker this claim is
    claim_text: str


ClaimNode = Annotated[CitedClaimNode | InferenceNode, Field(discriminator="kind")]


class RecallRef(BaseModel):
    """A `RECALL` hit -- a pointer to another node elsewhere in a session
    graph, never a duplicate of its content (see ADR-019's storage-vs-
    context distinction). Resolved/dereferenced only in the in-memory
    context assembly for the turn that recalled it."""
    node_id: str
    node_kind: str
    # None = the node lives in this same chat's own graph (the original,
    # single-chat RECALL). Set to another chat's slug for a cross-chat
    # RECALL hit -- required to disambiguate `node_id`, which is only
    # unique within one chat's own graph, not across `.sess` files.
    chat_slug: str | None = None


# ── Chat (ADR-019): pure-JSON `.sess` storage, two-layer + graph model ────────
# Session layer (this class + TurnNode: flow -- who said what, tool calls,
# reasoning, claims, model) vs. text layer (RichContent, schema_gov: the
# actual message content, format-tagged so it can grow beyond markdown
# later). A chat is a main line of TurnNodes (list order = NEXT, implicit,
# no edge objects needed); everything else -- tool calls, reasoning,
# claims, past regeneration attempts, recalls -- branches off one, never on
# the main line itself. See docs/concepts/chat-session-graph.md.


class TurnNode(BaseModel):
    id: str = Field(default_factory=_new_id)
    role: ChatRole
    content: RichContent
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # The model that actually generated this message -- None for user
    # messages. Distinct from Chat.model (the chat's *current* configured
    # model, overwritten on every turn, see VaultService.save_chat's
    # docstring): that field alone can't answer "which model produced THIS
    # specific historical reply" once the config changes mid-chat, which
    # matters when comparing model quality across a test session.
    model: str | None = None
    tool_calls: list[ToolCallNode] = Field(default_factory=list)
    thoughts: list[ThinkingNode] = Field(default_factory=list)
    claims: list[ClaimNode] = Field(default_factory=list)
    # Preserved previous attempts when this turn was regenerated (2026-08-04
    # decision: preserve, don't discard) -- each alternate is a full
    # historical TurnNode, own `model` included, so different models'
    # answers to the same prompt stay comparable, not just the current one.
    alternates: list["TurnNode"] = Field(default_factory=list)
    recalls: list[RecallRef] = Field(default_factory=list)


def _migrate_message_v1_to_v2(msg: dict) -> dict | TurnNode:
    if not isinstance(msg, dict):
        return msg  # already a constructed TurnNode -- e.g. Chat(messages=[TurnNode(...)])
                    # built directly in Python, not loaded from raw v1 JSON; nothing to migrate
    claims: list[dict] = []
    for fn in msg.get("footnotes", []) or []:
        claim_text = fn.get("claim_text") or ""
        index = fn.get("index", len(claims) + 1)
        if fn.get("relation") == "ai-inference":
            claims.append({"kind": "inference", "index": index, "claim_text": claim_text})
        else:
            claims.append({
                "kind": "claim", "index": index, "claim_text": claim_text,
                "sources": fn.get("sources", []), "relation": fn.get("relation"),
                "faithfulness_checked": fn.get("faithfulness_checked"),
            })
    tool_calls = [
        {"tool": tc.get("tool"), "args": tc.get("args", {}), "result": None, "status": "ok"}
        for tc in msg.get("tool_calls", []) or []
    ]
    out = {
        "role": msg.get("role"),
        "content": msg.get("content"),
        "model": msg.get("model"),
        "tool_calls": tool_calls,
        "claims": claims,
        "alternates": [_migrate_message_v1_to_v2(a) for a in msg.get("alternates", []) or []],
    }
    if msg.get("timestamp") is not None:
        out["timestamp"] = msg["timestamp"]
    return out


def _migrate_chat_v1_to_v2(raw: dict) -> dict:
    """v1's flat `ChatMessage` (`footnotes`/`tool_calls` summaries, no
    persisted tool results) -> v2's `TurnNode` (claims split into
    CitedClaimNode/InferenceNode, tool call results absent -- v1 never
    persisted them, so `RECALL` finds nothing to inline for migrated turns
    until they're regenerated). No `thoughts`/`recalls` for migrated data --
    neither existed in v1."""
    raw = dict(raw)
    raw["messages"] = [_migrate_message_v1_to_v2(m) for m in raw.get("messages", []) or []]
    return raw


class Chat(VaultNodeBase, VersionedModel):
    SCHEMA_VERSION = CHAT_SCHEMA_VERSION
    MIGRATIONS = {1: _migrate_chat_v1_to_v2}

    node_type: Literal[NodeType.chat] = NodeType.chat
    messages: list[TurnNode] = Field(default_factory=list)
    context_slugs: list[str] = Field(default_factory=list)
    model: str = "llama3"
    # Indices into `messages` that are currently pinned — same identity
    # convention DELETE /chats/{slug}/messages/{index} already uses. One
    # Excerpt per chat (ADR-015), not N independent notes: pinning/unpinning
    # a turn regenerates the single `excerpt_slug` note's Summary + raw copy
    # from whatever's currently pinned, rather than creating a new note.
    pinned_turns: list[int] = Field(default_factory=list)
    excerpt_slug: str | None = None
    # Populated only in API responses (app.py), never persisted — vault.py's
    # get_chat() leaves these at their defaults; it has no ChatAgent access
    # to compute a real estimate. The context-usage label (ADR-015).
    context_tokens_used: int = 0
    context_tokens_max: int = 0
    # True while a background thread is regenerating the Excerpt note after
    # a pin/unpin (app.py's _excerpt_regenerating registry) — not persisted,
    # in-memory only. The UI keeps showing the *previous* Excerpt content
    # while this is true, with a visible "regenerating" indicator, rather
    # than blocking the pin action on a synchronous LLM call.
    excerpt_regenerating: bool = False
    # Rendered HTML of just the Summary portion of the Excerpt note (split
    # server-side on the "## Pinned turns" marker _render_excerpt_body
    # always emits) — None if there's no Excerpt yet, or verbatim mode
    # produced no Summary at all. The UI shows this on its own; the raw
    # pinned turns are shown as a separate clickable list built directly
    # from pinned_turns + messages, not from re-rendering the note's own
    # "Pinned turns" section — clicking an item scrolls/highlights that
    # turn in the rolling conversation instead of duplicating its text.
    excerpt_summary_html: str | None = None


class Stream(VaultNodeBase):
    node_type: Literal[NodeType.stream] = NodeType.stream
    query: str
    description: str | None = None
    status: StreamStatus = StreamStatus.active
    refresh_frequency: RefreshFrequency = RefreshFrequency.weekly
    collection_key: str | None = None
    total_papers: int = 0
    last_updated: datetime | None = None
    next_update: datetime | None = None
    body: str = ""


# ── DSL link types ────────────────────────────────────────────────────────────

class WikiLink(BaseModel):
    source_slug: str
    target_slug: str
    section: str | None = None
    resolved: bool = True


class Transclusion(BaseModel):
    source_slug: str
    target_slug: str
    section: str | None = None
    depth: int = 0


class Citation(BaseModel):
    source_slug: str
    citekey: str
    resolved: bool = True


# ── Listing / API response helpers ───────────────────────────────────────────

class VaultNodeMeta(BaseModel):
    """Lightweight summary for sidebar listing — no body content."""
    slug: str
    title: str
    node_type: NodeType
    tags: list[str]
    modified_at: datetime
    # Source-only extras
    citekey: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    original_ext: str | None = None
    # Stream-only extras
    query: str | None = None
    stream_status: StreamStatus | None = None
    refresh_frequency: RefreshFrequency | None = None
    total_papers: int = 0
    last_updated: datetime | None = None
    next_update: datetime | None = None


class VaultListing(BaseModel):
    sources: list[VaultNodeMeta]
    notes: list[VaultNodeMeta]
    chats: list[VaultNodeMeta]
    streams: list[VaultNodeMeta] = Field(default_factory=list)


class VaultTreeNode(BaseModel):
    """One entry in the sidebar tree — either a directory or a vault file."""
    name: str
    kind: str                        # "dir" | "file"
    children: list["VaultTreeNode"] = Field(default_factory=list)
    # file-only fields
    slug: str | None = None
    title: str | None = None
    node_type: NodeType | None = None
    modified_at: datetime | None = None
    stream_status: StreamStatus | None = None


class RenderedNode(BaseModel):
    slug: str
    title: str
    node_type: NodeType
    html: str
    broken_links: list[str] = Field(default_factory=list)
    broken_citations: list[str] = Field(default_factory=list)
    original_ext: str | None = None
    has_md: bool = False
    # Stream-only — echoed back so the UI can render controls
    stream_status: StreamStatus | None = None
    refresh_frequency: RefreshFrequency | None = None
    total_papers: int = 0
    last_updated: datetime | None = None
    next_update: datetime | None = None
    query: str | None = None
    collection_key: str | None = None


class StreamRunResult(BaseModel):
    slug: str
    papers_found: int
    papers_saved: int
    papers_skipped_llm: int = 0
    sources_used: list[str]
    sources_skipped: list[str]
    errors: list[str] = []
