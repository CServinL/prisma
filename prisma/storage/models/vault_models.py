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
    # ADR-020: bibliographic fields APA citation formatting needs beyond
    # author/year/title -- all already fetched from Zotero at import time
    # (ZoteroItem has every one of these) but previously discarded rather
    # than persisted. url specifically fixes a standing bug: it was being
    # written into frontmatter by create_source_from_citekey() but never
    # read back out by get_source() -- silently dropped on every load.
    journal: str | None = None  # Zotero's publicationTitle -- journal/venue name
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    url: str | None = None
    # Zotero's raw itemType (e.g. "journalArticle", "book", "webpage") --
    # the APA template selector. Distinct from source_kind (paper/document/
    # web/media), which is a coarser 4-value classification predating this;
    # item_type is additive, not a replacement for it.
    item_type: str | None = None


CHAT_SCHEMA_VERSION = 3


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


class Qualifier(str, Enum):
    """Toulmin model's epistemic-strength modifier on a claim -- `tentative`
    doubles as "this is a hypothesis, not yet established." See
    docs/concepts/chat-session-graph.md's Argumentation structure section."""
    certain = "certain"
    probable = "probable"
    possible = "possible"
    tentative = "tentative"


class WarrantNode(BaseModel):
    """Toulmin model's Warrant -- the reasoning bridge explaining *why* a
    claim's grounds (`sources`) support that specific claim, often left
    implicit in informal writing but required explicit in formal academic
    argument. `backing` is the Toulmin Backing: support for the warrant
    itself, structurally identical to `sources` (a list of vault-node
    references), so it's a field here rather than its own node type.
    Schema support only -- nothing populates this yet. See
    docs/concepts/chat-session-graph.md's Argumentation structure section."""
    id: str = Field(default_factory=_new_id)
    text: str
    backing: list[str] = Field(default_factory=list)  # Note/Source/Chat slugs


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
    # Toulmin model extension (schema support only, nothing populates these
    # yet -- see docs/concepts/chat-session-graph.md):
    qualifier: Qualifier | None = None
    warrant: WarrantNode | None = None  # containment, like alternates -- at most one
    rebuts: str | None = None  # another ClaimNode's id this one contradicts/excepts


class InferenceNode(BaseModel):
    """A claim that's the model's own reasoning, traceable to no specific
    vault document -- structurally distinct from CitedClaimNode (no
    `sources`, nothing for `faithfulness_checked` to check), not the same
    shape with empty fields."""
    id: str = Field(default_factory=_new_id)
    kind: Literal["inference"] = "inference"
    index: int  # sequential per turn, 1-based -- the inline [^N] marker this claim is
    claim_text: str
    # Toulmin model extension -- see CitedClaimNode above.
    qualifier: Qualifier | None = None
    warrant: WarrantNode | None = None
    rebuts: str | None = None


ClaimNode = Annotated[CitedClaimNode | InferenceNode, Field(discriminator="kind")]


class MediaKind(str, Enum):
    svg = "svg"
    latex = "latex"
    drawio = "drawio"
    jpg = "jpg"
    pdf = "pdf"


class InlineMediaNode(BaseModel):
    """A media artifact whose content is small, text-based, and stored
    inline -- svg/latex/drawio are all XML or plain-text source, one shape
    for all three since they're structurally identical, not a class per
    format. See `AssetMediaNode` for the genuinely different binary case."""
    id: str = Field(default_factory=_new_id)
    kind: Literal[MediaKind.svg, MediaKind.latex, MediaKind.drawio]
    value: str
    caption: str | None = None


class AssetMediaNode(BaseModel):
    """A media artifact too large/binary to inline (jpg, pdf) -- stored as a
    vault-relative path served via vault/assets/, never base64-inlined into
    the .sess file. Split from `InlineMediaNode` because the two are
    genuinely different shapes (`value` vs. `asset_path`) -- same reasoning
    `CitedClaimNode`/`InferenceNode` were split on, not one class with two
    fields where exactly one is always None. `pdf` is the one kind that also
    has a promotion path to a real vault Note (see VaultService.promote_
    attachment_to_note) -- PDF text is worth extracting/indexing, unlike a
    bare jpg."""
    id: str = Field(default_factory=_new_id)
    kind: Literal[MediaKind.jpg, MediaKind.pdf]
    asset_path: str
    caption: str | None = None


# A media artifact attached to a turn -- either the assistant's own output
# (`TurnNode.media`, `PRODUCES` edge) or something a human turn brought in
# as input (`TurnNode.attachments`, `ATTACHES` edge). Same two concrete
# types either way; direction is carried by which edge points at it, not by
# more types. Schema support only -- no generator/renderer pipeline exists
# for any of the four kinds yet. See docs/concepts/chat-session-graph.md's
# Media nodes / Attachments sections.
MediaNode = Annotated[InlineMediaNode | AssetMediaNode, Field(discriminator="kind")]


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
    # v3 additions (schema support only, see docs/concepts/chat-session-graph.md):
    media: list[MediaNode] = Field(default_factory=list)         # assistant output, PRODUCES
    attachments: list[MediaNode] = Field(default_factory=list)   # human input, ATTACHES
    attached_slugs: list[str] = Field(default_factory=list)      # human input, REFERENCES
                                                                   # -- vault Note/Source/Chat slugs


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


def _migrate_chat_v2_to_v3(raw: dict) -> dict:
    """v2 -> v3 (Toulmin extension, MediaNode, attachments) adds only new
    optional fields with defaults (`qualifier`/`warrant`/`rebuts` on claims;
    `media`/`attachments`/`attached_slugs` on turns) -- no v2 shape is
    reinterpreted or restructured, so there is nothing to transform. Kept as
    an explicit identity step (not a bare MIGRATIONS omission) because
    VersionedModel requires one callable per version it upgrades through;
    the no-op *is* the correct migration for a purely-additive bump."""
    return raw


class Chat(VaultNodeBase, VersionedModel):
    SCHEMA_VERSION = CHAT_SCHEMA_VERSION
    MIGRATIONS = {1: _migrate_chat_v1_to_v2, 2: _migrate_chat_v2_to_v3}

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
