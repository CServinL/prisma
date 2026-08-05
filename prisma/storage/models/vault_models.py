from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from prisma.schema_gov import RichContent, VersionedModel


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


class ToolCallRecord(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class FootnoteRelation(str, Enum):
    # See docs/ontologia.md Axiom 16 and docs/concepts/footnote.md. Distinct
    # from Axiom 5 ("grounded" — chat-wide context scope): this is per-claim,
    # output-side attribution — what kind of sourcing backs THIS claim, not
    # what the chat as a whole was allowed to read.
    citation = "citation"  # direct quote / close paraphrase of one passage
    attribution = "attribution"  # synthesized/paraphrased from one document
    relational = "relational"  # connects/synthesizes across multiple documents
    ai_inference = "ai-inference"  # model's own reasoning, no vault source


class Footnote(BaseModel):
    index: int  # sequential per message, 1-based — the superscript number shown inline
    relation: FootnoteRelation
    sources: list[str] = Field(default_factory=list)  # Note/Source slugs; empty only for ai_inference
    claim_text: str | None = None  # span of ChatMessage.content this footnote covers
    # Whether an automated/manual check confirmed the claim accurately represents
    # `sources`. Orthogonal to `relation`, not a relation value itself — only
    # meaningful when `sources` is non-empty. None = not (yet) checked.
    faithfulness_checked: bool | None = None


# ── Chat (ADR-019): pure-JSON `.sess` storage, two-layer model ────────────────
# Session layer (this class + ChatMessage: flow -- who said what, tool calls,
# footnotes, model) vs. text layer (RichContent, schema_gov: the actual
# message content, format-tagged so it can grow beyond markdown later).

CHAT_SCHEMA_VERSION = 1


class ChatMessage(BaseModel):
    role: ChatRole
    content: RichContent
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    footnotes: list[Footnote] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    # The model that actually generated this message -- None for user
    # messages. Distinct from Chat.model (the chat's *current* configured
    # model, overwritten on every turn, see VaultService.save_chat's
    # docstring): that field alone can't answer "which model produced THIS
    # specific historical reply" once the config changes mid-chat, which
    # matters when comparing model quality across a test session.
    model: str | None = None
    # Preserved previous attempts when this turn was regenerated (2026-08-04
    # decision: preserve, don't discard) -- each alternate is a full
    # historical ChatMessage, own `model` included, so different models'
    # answers to the same prompt stay comparable, not just the current one.
    alternates: list["ChatMessage"] = Field(default_factory=list)


class Chat(VaultNodeBase, VersionedModel):
    SCHEMA_VERSION = CHAT_SCHEMA_VERSION

    node_type: Literal[NodeType.chat] = NodeType.chat
    messages: list[ChatMessage] = Field(default_factory=list)
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
