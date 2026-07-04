from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    promoted_from_chat: str | None = None
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
    # Companion lives at sources/<slug><original_ext>. None when only .md exists.
    original_ext: str | None = None


class ToolCallRecord(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: ChatRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sources_cited: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class Chat(VaultNodeBase):
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
