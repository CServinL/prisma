from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterator

import yaml

from prisma.storage.models.vault_models import (
    Chat, ChatMessage, ChatRole, Note, NodeType, Source, Stream, StreamStatus,
    RefreshFrequency, ToolCallRecord, VaultListing, VaultNodeMeta, VaultTreeNode,
)

# Recognised companion file extensions stored alongside a .md source node.
COMPANION_EXTS = (".pdf", ".html", ".htm", ".svg", ".epub", ".docx")

# Directories that are never part of the vault (graph indexer output, VCS, hidden).
_SKIP_DIRS = {"graphify-out", "kg-out", ".git", ".svn", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "untitled"


def _file_slug(stem: str) -> str:
    """Turn a filesystem stem into a URL-safe slug, preserving case."""
    slug = re.sub(r"[^a-zA-Z0-9\-_\.]", "-", stem)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "untitled"


def _parse_frontmatter(body: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_without_frontmatter).

    Accepts YAML --- blocks and the legacy HTML-comment style so existing
    files keep working after the migration.
    """
    # YAML frontmatter
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            raw = body[3:end].strip()
            rest = body[end + 4:].lstrip("\n")
            try:
                fm = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, rest

    # Legacy HTML comment frontmatter — extract known fields so old files still parse.
    fm: dict = {}
    patterns = {
        "tags": re.compile(r"^<!--\s*tags:(.*?)-->", re.MULTILINE),
        "citekey": re.compile(r"^<!--\s*citekey:\s*(\S+)\s*-->", re.MULTILINE),
        "authors": re.compile(r"^<!--\s*authors:(.*?)-->", re.MULTILINE),
        "year": re.compile(r"^<!--\s*year:\s*(\d{4})\s*-->", re.MULTILINE),
    }
    for key, pat in patterns.items():
        m = pat.search(body)
        if not m:
            continue
        raw = m.group(1).strip()
        if key == "tags":
            fm[key] = [t.strip() for t in raw.split(",") if t.strip()]
        elif key == "authors":
            fm[key] = [a.strip() for a in raw.split(",") if a.strip()]
        elif key == "year":
            fm[key] = int(raw)
        else:
            fm[key] = raw
    return fm, body


def _render_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True) + "---\n\n"


# Chat transcripts are stored as plain markdown (no database, no HTML) —
# role is carried by a heading per turn so any plain markdown viewer still
# renders a readable transcript; the app parses on these headings to style
# turns differently (user vs. assistant) at render time.
_CHAT_ROLE_HEADING = {ChatRole.user: "You", ChatRole.assistant: "Prisma"}
_CHAT_HEADING_ROLE = {v: k for k, v in _CHAT_ROLE_HEADING.items()}
_CHAT_TURN_RE = re.compile(r"^### (You|Prisma)\s*$\n(.*?)(?=^### (?:You|Prisma)\s*$|\Z)", re.MULTILINE | re.DOTALL)
_CHAT_TOOL_LINE_RE = re.compile(r"^>\s*(?:🔧\s*)?used\s*`([a-zA-Z0-9_]+)`:\s*(.*)$", re.MULTILINE)


def _render_chat_body(messages: list[ChatMessage]) -> str:
    parts = []
    for msg in messages:
        heading = _CHAT_ROLE_HEADING[msg.role]
        parts.append(f"### {heading}\n")
        for tc in msg.tool_calls:
            parts.append(f"> used `{tc.tool}`: {tc.args.get('query', '')}\n")
        if msg.tool_calls:
            parts.append("\n")
        parts.append(f"{msg.content}\n\n")
    return "".join(parts)


def _render_excerpt_body(summary: str | None, raw_turns: list[ChatMessage]) -> str:
    """Summary on top (verbatim mode: omitted — see ADR-015's mode switch),
    verbatim pinned turns below, each its own heading + block (same
    `### You`/`### Prisma` convention _render_chat_body uses for the main
    transcript, separated by a rule) rather than run together — see
    VaultService.save_excerpt."""
    parts = [f"## Summary\n\n{summary.strip()}\n\n## Pinned turns\n"] if summary is not None else ["## Pinned turns\n"]
    for i, msg in enumerate(raw_turns):
        heading = _CHAT_ROLE_HEADING[msg.role]
        if i > 0:
            parts.append("\n---\n")
        parts.append(f"\n### {heading}\n\n{msg.content}\n")
    return "".join(parts)


def _parse_chat_body(body: str) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for heading, turn_body in _CHAT_TURN_RE.findall(body):
        role = _CHAT_HEADING_ROLE[heading]
        tool_calls = [
            ToolCallRecord(tool=tool, args={"query": query})
            for tool, query in _CHAT_TOOL_LINE_RE.findall(turn_body)
        ]
        content = _CHAT_TOOL_LINE_RE.sub("", turn_body).strip()
        messages.append(ChatMessage(role=role, content=content, tool_calls=tool_calls))
    return messages


def _first_heading(body: str) -> str | None:
    m = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _inline_tags(body: str) -> list[str]:
    return [t for t in re.findall(r"(?<!\[)#([a-zA-Z][a-zA-Z0-9_\-]*)", body)]


def _parse_dt(val: object) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def _companion_ext(md_path: Path) -> str | None:
    for ext in COMPANION_EXTS:
        if md_path.with_suffix(ext).exists():
            return ext
    return None


class VaultService:
    def __init__(
        self,
        vault_root: Path | str | None = None,
        default_notes: str = "notes",
        default_sources: str = "sources",
        default_chats: str = "chats",
    ) -> None:
        self.root = Path(vault_root or Path.home() / "prisma-vault").expanduser().resolve()
        # Default directories for *creating* new files — user can reorganise freely.
        # These are relative to vault root and only created on ensure_dirs().
        self.default_dirs = {
            NodeType.note: self.root / default_notes,
            NodeType.source: self.root / default_sources,
            NodeType.chat: self.root / default_chats,
            NodeType.stream: self.root / "streams",
        }
        # Every chat write (save_chat/set_pinned_turns/save_excerpt) is a
        # plain read-parse-write of a whole file with no locking — two
        # requests for the same chat overlapping (e.g. quick successive
        # pin/unpin clicks, or a pin racing a slow /chat completion) can
        # each read stale state and one write silently clobbers the other's
        # change. Chat writes are low-frequency; one process-wide lock is
        # simple and sufficient — no need for per-slug lock management.
        self._chat_write_lock = threading.Lock()

    def ensure_dirs(self) -> None:
        for d in self.default_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    # ── Internal traversal ────────────────────────────────────────────────────

    def _all_md_files(self) -> Iterator[Path]:
        if not self.root.exists():
            return
        import os
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=True):
            # Prune skip dirs and hidden dirs in-place so os.walk won't descend into them
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            for fname in filenames:
                if fname.endswith(".md"):
                    yield Path(dirpath) / fname

    def _find_md(self, slug: str) -> Path | None:
        """Find a .md file whose slug matches. Does NOT find .html files."""
        slug_norm = _file_slug(slug).lower()
        for path in self._all_md_files():
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def _find_file(self, slug: str) -> Path | None:
        """Find a .md or .html file whose slug matches."""
        md = self._find_md(slug)
        if md is not None:
            return md
        # Path-relative slugs encode '/' as '--' (e.g. "papers--bricken2003--index")
        if "--" in slug:
            candidate = (self.root / slug.replace("--", "/")).with_suffix(".html")
            if candidate.exists():
                return candidate
        slug_norm = _file_slug(slug).lower()
        import os
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=True):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.endswith(".html"):
                    stem = fname[:-5]
                    if _file_slug(stem).lower() == slug_norm:
                        return Path(dirpath) / fname
        return None

    def _node_type_from_fm(self, fm: dict) -> NodeType:
        raw = fm.get("type", "note")
        try:
            return NodeType(raw)
        except ValueError:
            return NodeType.note

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_nodes(self, node_type: NodeType | None = None) -> VaultListing:
        buckets: dict[NodeType, list[VaultNodeMeta]] = {t: [] for t in NodeType}
        for path in self._all_md_files():
            body = path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(body)
            nt = self._node_type_from_fm(fm)
            if node_type and nt != node_type:
                continue
            if nt == NodeType.stream:
                continue  # streams are .yaml, not .md
            buckets[nt].append(self._meta_from_file(path, fm, content, nt))

        if not node_type or node_type == NodeType.stream:
            for s in self.list_streams():
                buckets[NodeType.stream].append(self._meta_from_stream(s))

        for nt in buckets:
            buckets[nt].sort(key=lambda m: m.modified_at, reverse=True)

        return VaultListing(
            sources=buckets[NodeType.source],
            notes=buckets[NodeType.note],
            chats=buckets[NodeType.chat],
            streams=buckets[NodeType.stream],
        )

    def _meta_from_file(self, path: Path, fm: dict, content: str, nt: NodeType) -> VaultNodeMeta:
        tags = list(fm.get("tags") or []) + _inline_tags(content)
        tags = list(dict.fromkeys(tags))
        meta = VaultNodeMeta(
            slug=_file_slug(path.stem),
            title=fm.get("title") or _first_heading(content) or path.stem,
            node_type=nt,
            tags=tags,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime),
            citekey=fm.get("citekey"),
            authors=list(fm.get("authors") or []),
            year=fm.get("year"),
            original_ext=_companion_ext(path) if nt == NodeType.source else None,
        )
        if nt == NodeType.stream:
            try:
                meta.stream_status = StreamStatus(fm.get("status", "active"))
            except ValueError:
                meta.stream_status = StreamStatus.active
            try:
                meta.refresh_frequency = RefreshFrequency(fm.get("refresh_frequency", "weekly"))
            except ValueError:
                meta.refresh_frequency = RefreshFrequency.weekly
            meta.query = fm.get("query")
            meta.total_papers = int(fm.get("total_papers", 0))
            meta.last_updated = _parse_dt(fm.get("last_updated"))
            meta.next_update = _parse_dt(fm.get("next_update"))
        return meta

    def _meta_from_stream(self, s: Stream) -> VaultNodeMeta:
        return VaultNodeMeta(
            slug=s.slug,
            title=s.title,
            node_type=NodeType.stream,
            tags=s.tags,
            modified_at=s.modified_at,
            query=s.query,
            stream_status=s.status,
            refresh_frequency=s.refresh_frequency,
            total_papers=s.total_papers,
            last_updated=s.last_updated,
            next_update=s.next_update,
        )

    # ── Get ───────────────────────────────────────────────────────────────────

    def get_note(self, slug: str) -> Note:
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"note not found: {slug!r}")
        body = path.read_text(encoding="utf-8")
        fm, content = _parse_frontmatter(body)
        stat = path.stat()
        tags = list(fm.get("tags") or []) + _inline_tags(content)
        return Note(
            slug=_file_slug(path.stem),
            title=fm.get("title") or _first_heading(content) or path.stem,
            tags=list(dict.fromkeys(tags)),
            body=content,
            promoted_from_chat=fm.get("promoted_from_chat"),
            path=path,
            created_at=datetime.fromtimestamp(stat.st_mtime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def get_source(self, slug: str) -> Source:
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"source not found: {slug!r}")
        body = path.read_text(encoding="utf-8")
        fm, content = _parse_frontmatter(body)
        stat = path.stat()
        tags = list(fm.get("tags") or []) + _inline_tags(content)
        return Source(
            slug=_file_slug(path.stem),
            title=fm.get("title") or _first_heading(content) or path.stem,
            tags=list(dict.fromkeys(tags)),
            citekey=fm.get("citekey") or _file_slug(path.stem),
            authors=list(fm.get("authors") or []),
            year=fm.get("year"),
            doi=fm.get("doi"),
            zotero_key=fm.get("zotero_key"),
            stream_id=fm.get("stream_id"),
            abstract=fm.get("abstract"),
            body=content,
            original_ext=_companion_ext(path),
            path=path,
            created_at=datetime.fromtimestamp(stat.st_mtime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def get_chat(self, slug: str) -> Chat:
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"chat not found: {slug!r}")
        body = path.read_text(encoding="utf-8")
        fm, content = _parse_frontmatter(body)
        stat = path.stat()
        return Chat(
            slug=_file_slug(path.stem),
            title=fm.get("title") or path.stem,
            tags=list(fm.get("tags") or []),
            messages=_parse_chat_body(content),
            model=fm.get("model", "llama3"),
            pinned_turns=list(fm.get("pinned_turns") or []),
            excerpt_slug=fm.get("excerpt_slug"),
            path=path,
            created_at=datetime.fromtimestamp(stat.st_mtime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def create_chat(self, title: str, model: str = "llama3") -> Chat:
        self.ensure_dirs()
        slug = self._unique_slug(_slugify(title))
        fm = {"type": "chat", "title": title, "model": model, "tags": ["chat"]}
        path = self.default_dirs[NodeType.chat] / f"{slug}.md"
        path.write_text(_render_frontmatter(fm), encoding="utf-8")
        return self.get_chat(slug)

    def save_chat(self, slug: str, messages: list[ChatMessage], model: str | None = None) -> Chat:
        """`model`, when given, overwrites the chat's stored frontmatter
        model — the model actually used for the turn just saved. Without
        this, a chat created before a model rename/merge (e.g.
        prisma-chat:7b -> prisma-llm:7b) would keep displaying its
        original, now-stale name forever, even though every subsequent
        turn actually used the current config's model."""
        with self._chat_write_lock:
            path = self._find_md(slug)
            if path is None:
                raise FileNotFoundError(f"chat not found: {slug!r}")
            existing = path.read_text(encoding="utf-8")
            fm, _ = _parse_frontmatter(existing)
            if model is not None:
                fm["model"] = model
            path.write_text(_render_frontmatter(fm) + _render_chat_body(messages), encoding="utf-8")
        return self.get_chat(slug)

    def append_messages(self, slug: str, new_messages: list[ChatMessage], model: str | None = None) -> Chat:
        """Atomically append to whatever the chat's *current* on-disk
        messages are, not a snapshot taken before some earlier operation
        (e.g. an LLM call) started. `/chat`'s handler used to read
        `history` before calling the model, then write `history +
        [new turns]` once the call finished — if a `DELETE
        /chats/{slug}/messages/{index}` landed in between, that stale
        write would silently revive the just-deleted message. Reading and
        writing under the same lock closes that window."""
        with self._chat_write_lock:
            path = self._find_md(slug)
            if path is None:
                raise FileNotFoundError(f"chat not found: {slug!r}")
            existing = path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(existing)
            if model is not None:
                fm["model"] = model
            current_messages = _parse_chat_body(content)
            path.write_text(
                _render_frontmatter(fm) + _render_chat_body(current_messages + new_messages), encoding="utf-8",
            )
        return self.get_chat(slug)

    def set_pinned_turns(self, chat_slug: str, indices: list[int]) -> Chat:
        """Write-only: records which turn indices are currently pinned.
        Does not regenerate the chat's single Excerpt note itself — that
        needs an LLM call (ADR-015's compressed-mode Summary), which this
        pure-storage layer has no access to. Callers (app.py) call this
        first, then assemble the new Summary and call save_excerpt()."""
        with self._chat_write_lock:
            chat_path = self._find_md(chat_slug)
            if chat_path is None:
                raise FileNotFoundError(f"chat not found: {chat_slug!r}")
            raw = chat_path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(raw)
            fm["pinned_turns"] = sorted(set(indices))
            chat_path.write_text(_render_frontmatter(fm) + content, encoding="utf-8")
        return self.get_chat(chat_slug)

    def save_excerpt(self, chat_slug: str, summary: str | None, raw_turns: list[ChatMessage]) -> Note:
        """Create or update the *one* Excerpt note for this chat (ADR-015)
        — Summary on top (verbatim mode: `summary=None`, no summary section
        at all — pinned turns are the whole point in that mode), verbatim
        copy of the pinned turns below. Reuses the existing note
        (`Chat.excerpt_slug`) if one was already created for this chat,
        rather than creating a new note per pin. If that note has since
        been deleted out from under `excerpt_slug` (e.g. via the generic
        delete-node endpoint, which has no special case for this), falls
        back to creating a fresh one instead of raising — otherwise every
        future pin/unpin for this chat would permanently fail with
        `FileNotFoundError`, silently swallowed by the background
        regeneration thread's blanket exception handler."""
        with self._chat_write_lock:
            chat = self.get_chat(chat_slug)
            body = _render_excerpt_body(summary, raw_turns)
            if chat.excerpt_slug:
                try:
                    return self.save_note(chat.excerpt_slug, body)
                except FileNotFoundError:
                    pass  # note deleted underneath us — fall through to create a fresh one
            note = self.create_note(f"Excerpt — {chat.title}", body=body, promoted_from_chat=chat_slug)
            chat_path = self._find_md(chat_slug)
            raw = chat_path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(raw)
            fm["excerpt_slug"] = note.slug
            chat_path.write_text(_render_frontmatter(fm) + content, encoding="utf-8")
            return note

    def get_any(self, slug: str) -> Note | Source | Chat | Stream:
        path = self._find_file(slug)
        if path is None:
            # streams are stored as .yaml, not .md — _find_file won't find them
            try:
                return self.get_stream(slug)
            except FileNotFoundError:
                pass
            raise FileNotFoundError(f"node not found in vault: {slug!r}")
        if path.suffix == ".html":
            stat = path.stat()
            companion_md = path.with_suffix(".md")
            html_fm: dict = {}
            if companion_md.exists():
                raw_md = companion_md.read_text(encoding="utf-8")
                html_fm, _ = _parse_frontmatter(raw_md)
            nt = self._node_type_from_fm(html_fm)
            return Note(
                slug=_file_slug(path.stem),
                title=html_fm.get("title", path.stem),
                body=path.read_text(encoding="utf-8"),
                path=path,
                node_type=nt,
                original_ext=".html",
                created_at=datetime.fromtimestamp(stat.st_mtime),
                modified_at=datetime.fromtimestamp(stat.st_mtime),
            )
        raw = path.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(raw)
        nt = self._node_type_from_fm(fm)
        if nt == NodeType.source:
            return self.get_source(slug)
        if nt == NodeType.stream:
            return self.get_stream(slug)
        if nt == NodeType.chat:
            return self.get_chat(slug)
        return self.get_note(slug)

    def slug_exists(self, slug: str) -> bool:
        return self._find_file(slug) is not None

    def body_of(self, slug: str) -> str | None:
        path = self._find_file(slug)
        if path is None:
            return None
        if path.suffix == ".html":
            return path.read_text(encoding="utf-8")
        _, content = _parse_frontmatter(path.read_text(encoding="utf-8"))
        return content

    def find_companion(self, slug: str) -> Path | None:
        path = self._find_md(slug)
        if path is None:
            return None
        for ext in COMPANION_EXTS:
            candidate = path.with_suffix(ext)
            if candidate.exists():
                return candidate
        return None

    def set_node_type(self, slug: str, node_type: NodeType) -> None:
        """Update the type field for any node. For HTML files, creates/updates a companion .md."""
        path = self._find_file(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        if path.suffix == ".html":
            companion_md = path.with_suffix(".md")
            if companion_md.exists():
                raw = companion_md.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(raw)
            else:
                fm, body = {"title": path.stem}, ""
            fm["type"] = node_type.value
            companion_md.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        else:
            raw = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(raw)
            fm["type"] = node_type.value
            path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")

    # ── Format generation ─────────────────────────────────────────────────────

    def ensure_md_format(self, html_path: Path) -> bool:
        """Convert an HTML file to Markdown and store it in the companion .md body.
        Returns True if the companion was created/updated, False if already present."""
        companion = html_path.with_suffix(".md")
        if companion.exists():
            raw = companion.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(raw)
            if body.strip():
                return False
        else:
            fm, body = {"title": html_path.stem}, ""
        try:
            from docu_craft import render as _dc_render
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
                tmp = Path(tf.name)
            _dc_render(source=html_path, format="md", output=tmp)
            md_content = tmp.read_text(encoding="utf-8")
            tmp.unlink(missing_ok=True)
        except Exception:
            return False
        fm.setdefault("type", "note")
        companion.write_text(_render_frontmatter(fm) + md_content, encoding="utf-8")
        return True

    def ensure_all_md_formats(self) -> int:
        """Generate MD companions for every HTML file that lacks body content. Returns count."""
        import os
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=True):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.endswith(".html"):
                    if self.ensure_md_format(Path(dirpath) / fname):
                        count += 1
        return count

    def get_md_body(self, html_path: Path) -> str | None:
        """Return the markdown body of a companion .md if it has content, else None."""
        companion = html_path.with_suffix(".md")
        if not companion.exists():
            return None
        _, body = _parse_frontmatter(companion.read_text(encoding="utf-8"))
        return body.strip() or None

    # ── Create / save ─────────────────────────────────────────────────────────

    def create_note(
        self, title: str, body: str = "", tags: list[str] | None = None,
        promoted_from_chat: str | None = None,
    ) -> Note:
        self.ensure_dirs()
        slug = self._unique_slug(_slugify(title))
        fm = {"type": "note", "title": title}
        if tags:
            fm["tags"] = tags
        if promoted_from_chat:
            fm["promoted_from_chat"] = promoted_from_chat
        path = self.default_dirs[NodeType.note] / f"{slug}.md"
        path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return self.get_note(slug)

    def save_note(self, slug: str, body: str) -> Note:
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"note not found: {slug!r}")
        existing = path.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(existing)
        path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return self.get_note(slug)

    def _unique_slug(self, base: str) -> str:
        slug = base
        n = 1
        while self._find_md(slug) is not None:
            slug = f"{base}-{n}"
            n += 1
        return slug

    def _unique_stream_slug(self, base: str) -> str:
        slug = base
        n = 1
        while (self.default_dirs[NodeType.stream] / f"{slug}.yaml").exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    # ── Streams (stored as .yaml — the knowledge graph indexer skips non-.md files) ─

    def _find_stream_path(self, slug: str) -> Path | None:
        slug_norm = _file_slug(slug).lower()
        streams_dir = self.default_dirs[NodeType.stream]
        if not streams_dir.exists():
            return None
        for path in streams_dir.glob("*.yaml"):
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def get_stream(self, slug: str) -> Stream:
        path = self._find_stream_path(slug)
        if path is None:
            raise FileNotFoundError(f"stream not found: {slug!r}")
        fm = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        stat = path.stat()
        try:
            status = StreamStatus(fm.get("status", "active"))
        except ValueError:
            status = StreamStatus.active
        try:
            frequency = RefreshFrequency(fm.get("refresh_frequency", "weekly"))
        except ValueError:
            frequency = RefreshFrequency.weekly
        return Stream(
            slug=_file_slug(path.stem),
            title=fm.get("title") or path.stem,
            tags=list(fm.get("tags") or []),
            query=fm.get("query", ""),
            description=fm.get("description"),
            status=status,
            refresh_frequency=frequency,
            collection_key=fm.get("collection_key"),
            total_papers=int(fm.get("total_papers", 0)),
            last_updated=_parse_dt(fm.get("last_updated")),
            next_update=_parse_dt(fm.get("next_update")),
            body="",
            path=path,
            created_at=datetime.fromtimestamp(stat.st_mtime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def list_streams(self) -> list[Stream]:
        streams_dir = self.default_dirs[NodeType.stream]
        if not streams_dir.exists():
            return []
        result = []
        for path in streams_dir.glob("*.yaml"):
            try:
                result.append(self.get_stream(_file_slug(path.stem)))
            except Exception:
                pass
        result.sort(key=lambda s: s.modified_at, reverse=True)
        return result

    def create_stream(
        self,
        title: str,
        query: str,
        description: str | None = None,
        refresh_frequency: str = "weekly",
        tags: list[str] | None = None,
    ) -> Stream:
        self.ensure_dirs()
        slug = self._unique_stream_slug(_slugify(title))
        data: dict = {
            "type": "stream",
            "title": title,
            "query": query,
            "status": "active",
            "refresh_frequency": refresh_frequency,
            "total_papers": 0,
        }
        if description:
            data["description"] = description
        if tags:
            data["tags"] = tags
        path = self.default_dirs[NodeType.stream] / f"{slug}.yaml"
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return self.get_stream(slug)

    def save_stream(self, slug: str, **updates: object) -> Stream:
        path = self._find_stream_path(slug)
        if path is None:
            raise FileNotFoundError(f"stream not found: {slug!r}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k, v in updates.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v.isoformat() if isinstance(v, datetime) else v
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return self.get_stream(slug)

    def append_stream_log(self, slug: str, entry: str) -> None:
        path = self._find_stream_path(slug)
        if path is None:
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        from datetime import date
        log = data.get("log") or []
        log.append({"date": date.today().isoformat(), "entry": entry})
        data["log"] = log
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ── Tree ─────────────────────────────────────────────────────────────────

    def get_tree(self) -> list[VaultTreeNode]:
        """Return the vault root as a list of top-level tree nodes."""
        if not self.root.exists():
            return []
        return self._tree_children(self.root)

    def _tree_children(self, directory: Path) -> list[VaultTreeNode]:
        import os
        nodes: list[VaultTreeNode] = []
        try:
            entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(follow_symlinks=True), e.name.lower()))
        except PermissionError:
            return nodes

        streams_dir_name = self.default_dirs[NodeType.stream].name
        for entry in entries:
            name = entry.name
            if name in _SKIP_DIRS or name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=True) and directory == self.root and name == streams_dir_name:
                continue  # streams shown in the dedicated sidebar section, not the tree
            if entry.is_dir(follow_symlinks=True):
                children = self._tree_children(Path(entry.path))
                if children:  # omit empty dirs
                    nodes.append(VaultTreeNode(name=name, kind="dir", children=children))
            elif name.endswith(".yaml") and directory == self.default_dirs[NodeType.stream]:
                try:
                    path = Path(entry.path)
                    fm = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    title = fm.get("title") or path.stem
                    stream_status = None
                    try:
                        stream_status = StreamStatus(fm.get("status", "active"))
                    except ValueError:
                        pass
                    nodes.append(VaultTreeNode(
                        name=name,
                        kind="file",
                        slug=_file_slug(path.stem),
                        title=title,
                        node_type=NodeType.stream,
                        modified_at=datetime.fromtimestamp(path.stat().st_mtime),
                        stream_status=stream_status,
                    ))
                except Exception:
                    pass
            elif name.endswith(".md") or name.endswith(".html"):
                try:
                    path = Path(entry.path)
                    if name.endswith(".md") and path.with_suffix(".html").exists():
                        continue  # sidecar metadata for an HTML file; shown via the .html entry
                    if name.endswith(".html"):
                        try:
                            rel = path.relative_to(self.root)
                            html_slug = str(rel.with_suffix("")).replace("/", "--").replace("\\", "--")
                        except ValueError:
                            html_slug = _file_slug(path.stem)
                        companion_md = path.with_suffix(".md")
                        html_nt = NodeType.note
                        if companion_md.exists():
                            raw_md = companion_md.read_text(encoding="utf-8")
                            html_fm, _ = _parse_frontmatter(raw_md)
                            html_nt = self._node_type_from_fm(html_fm)
                        nodes.append(VaultTreeNode(
                            name=name,
                            kind="file",
                            slug=html_slug,
                            title=path.stem,
                            node_type=html_nt,
                            modified_at=datetime.fromtimestamp(path.stat().st_mtime),
                        ))
                    else:
                        raw = path.read_text(encoding="utf-8")
                        fm, content = _parse_frontmatter(raw)
                        nt = self._node_type_from_fm(fm)
                        title = fm.get("title") or _first_heading(content) or path.stem
                        stream_status = None
                        if nt == NodeType.stream:
                            try:
                                stream_status = StreamStatus(fm.get("status", "active"))
                            except ValueError:
                                pass
                        nodes.append(VaultTreeNode(
                            name=name,
                            kind="file",
                            slug=_file_slug(path.stem),
                            title=title,
                            node_type=nt,
                            modified_at=datetime.fromtimestamp(path.stat().st_mtime),
                            stream_status=stream_status,
                        ))
                except Exception:
                    pass
        return nodes

    # ── Node operations ───────────────────────────────────────────────────────

    def move_node(self, slug: str, dest_dir: str) -> str:
        path = self._find_file(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        # Normalise without resolving symlinks — resolve() follows them out of vault
        dest = (self.root / dest_dir).absolute()
        if ".." in Path(dest_dir).parts:
            raise ValueError("destination outside vault")
        dest.mkdir(parents=True, exist_ok=True)
        new_path = dest / path.name
        if new_path.exists() and new_path != path:
            raise FileExistsError(f"file already exists at destination: {new_path.name}")
        path.rename(new_path)
        # companion .md if moving an .html file
        if path.suffix == ".html":
            companion = path.with_suffix(".md")
            if companion.exists():
                companion.rename(dest / companion.name)
        rel = new_path.relative_to(self.root)
        return str(rel.with_suffix("")).replace("/", "--").replace("\\", "--")

    def rename_node(self, slug: str, new_title: str) -> str:
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        new_stem = _slugify(new_title)
        new_path = path.parent / f"{new_stem}.md"
        if new_path.exists() and new_path != path:
            raise FileExistsError(f"a file named {new_stem!r} already exists")
        raw = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(raw)
        fm["title"] = new_title
        path.rename(new_path)
        new_path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return _file_slug(new_stem)

    def delete_node(self, slug: str) -> None:
        path = self._find_file(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        path.unlink()
        companion = path.with_suffix(".md") if path.suffix == ".html" else None
        if companion and companion.exists():
            companion.unlink()

    def create_dir(self, rel_path: str) -> None:
        if ".." in Path(rel_path).parts:
            raise ValueError("path outside vault")
        (self.root / rel_path).mkdir(parents=True, exist_ok=True)

    def delete_stream(self, slug: str) -> None:
        path = self._find_stream_path(slug)
        if path is None:
            raise FileNotFoundError(f"stream not found: {slug!r}")
        path.unlink()
