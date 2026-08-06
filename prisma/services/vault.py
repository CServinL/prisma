from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterator

import yaml

from prisma.schema_gov import ContentFormat, RichContent
from prisma.storage.models.vault_models import (
    Chat, ChatRole, Note, NodeType, Source, Stream, StreamStatus,
    RefreshFrequency, TurnNode, VaultListing, VaultNodeMeta, VaultTreeNode,
    _migrate_message_v1_to_v2,
)

_log = logging.getLogger("prisma.vault")

# Recognised companion file extensions stored alongside a .md source node.
COMPANION_EXTS = (".pdf", ".html", ".htm", ".svg", ".epub", ".docx")

# Directories that are never part of the vault (VCS, build artifacts, hidden).
# Internal app state (chromadb/, kg-out/) lives under .vault-files/ instead of
# being listed here by name — the leading-dot rule below already excludes it,
# the same way .git is excluded, so a new internal dir never needs a new entry.
_SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


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


# ── Legacy chat .md format (ADR-019) ─────────────────────────────────────────
# Chats used to be stored as plain markdown -- role carried by a heading per
# turn, tool calls as `>` blockquote lines, model/footnotes as a
# `<!-- prisma:meta {...} -->` JSON comment. Superseded by pure-JSON `.sess`
# files (see load_chat_session/save_chat_session below); every *live*
# VaultService chat method now reads/writes `.sess` only. This block stays
# read-only, solely so `chat_migration.migrate_chats_to_sess` can convert a
# real vault's pre-existing chat `.md` files -- once a vault has no `.md`
# files left under its chats directory, this whole block can be deleted.
_CHAT_ROLE_HEADING = {ChatRole.user: "You", ChatRole.assistant: "Prisma"}
_CHAT_HEADING_ROLE = {v: k for k, v in _CHAT_ROLE_HEADING.items()}
_CHAT_TURN_RE = re.compile(r"^### (You|Prisma)\s*$\n(.*?)(?=^### (?:You|Prisma)\s*$|\Z)", re.MULTILINE | re.DOTALL)
_CHAT_TOOL_LINE_RE = re.compile(r"^>\s*(?:🔧\s*)?used\s*`([a-zA-Z0-9_]+)`:\s*(.*)$", re.MULTILINE)
_CHAT_META_LINE_RE = re.compile(r"^<!--\s*prisma:meta\s+(.+?)\s*-->\s*$", re.MULTILINE)

# Governance for the prisma:meta blob's own shape, independent of Pydantic's
# per-field defaults on TurnNode/its claim types themselves (which only
# handle *adding* an optional field, not a rename or a meaning change).
CHAT_META_SCHEMA_VERSION = 1


def _migrate_chat_meta(raw: dict) -> dict:
    """Upgrades a raw prisma:meta dict to the current shape before its
    contents are used. Absent schema_version means "written before this
    field existed" (2026-08-04 same-day code) -- already shape v1, the
    version this blob was introduced at, so it's treated as v1 rather than
    rejected. Raises ValueError for a version newer than this build knows
    (an older binary reading a file a newer one wrote) -- the caller
    already catches ValueError around the whole meta-comment parse and
    degrades to "no metadata for this turn," so this composes for free
    with the existing defensive-parsing contract, no new handling needed
    here or at the call site.

    Next format change adds a step here, e.g.:
        if version == 1:
            raw = {...upgraded...}
            version = 2
    Never rewrite an existing step once shipped -- each version's upgrade
    path must stay correct for a file frozen at that version, however old."""
    version = raw.get("schema_version", 1)
    if version > CHAT_META_SCHEMA_VERSION:
        raise ValueError(
            f"prisma:meta schema_version {version} is newer than this build "
            f"supports ({CHAT_META_SCHEMA_VERSION})"
        )
    return raw


def _render_excerpt_body(summary: str | None, raw_turns: list[TurnNode]) -> str:
    """Summary on top (verbatim mode: omitted — see ADR-015's mode switch),
    verbatim pinned turns below, each its own heading + block (`### You`/
    `### Prisma`, same convention the legacy chat `.md` format used, separated
    by a rule) rather than run together — see VaultService.save_excerpt. The
    Excerpt note itself stays a real `.md` Note (ADR-019's two-layer model:
    only the Excerpt is genuine prose), unaffected by chats moving to `.sess`."""
    parts = [f"## Summary\n\n{summary.strip()}\n\n## Pinned turns\n"] if summary is not None else ["## Pinned turns\n"]
    for i, msg in enumerate(raw_turns):
        heading = _CHAT_ROLE_HEADING[msg.role]
        if i > 0:
            parts.append("\n---\n")
        parts.append(f"\n### {heading}\n\n{msg.content.value}\n")
    return "".join(parts)


def _parse_chat_body(body: str) -> list[TurnNode]:
    """Legacy `.md` read path -- see the block comment above. Builds the old
    flat (role/content/tool_calls/footnotes) shape per turn, then reuses
    `_migrate_message_v1_to_v2` (the same v1->v2 `.sess` migration logic) to
    get the current `TurnNode` shape directly, rather than duplicating the
    footnote-to-claim/tool-call mapping a second time."""
    messages: list[TurnNode] = []
    for heading, turn_body in _CHAT_TURN_RE.findall(body):
        role = _CHAT_HEADING_ROLE[heading]
        tool_calls = [
            {"tool": tool, "args": {"query": query}}
            for tool, query in _CHAT_TOOL_LINE_RE.findall(turn_body)
        ]
        model: str | None = None
        footnotes: list[dict] = []
        meta_match = _CHAT_META_LINE_RE.search(turn_body)
        if meta_match:
            try:
                meta = _migrate_chat_meta(json.loads(meta_match.group(1)))
                model = meta.get("model")
                footnotes = meta.get("footnotes", [])
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                # A hand-edited or corrupted meta line degrades to "no
                # metadata," never breaks loading the rest of the chat --
                # same defensive posture ADR-017's FOOTNOTES_JSON parsing
                # already takes on the model's own self-report.
                _log.warning("chat turn: malformed prisma:meta comment, dropping: %s", exc)
        content = _CHAT_TOOL_LINE_RE.sub("", turn_body)
        content = _CHAT_META_LINE_RE.sub("", content).strip()
        raw = _migrate_message_v1_to_v2({
            "role": role.value,
            "content": RichContent(format=ContentFormat.markdown, value=content).model_dump(mode="json"),
            "model": model, "tool_calls": tool_calls, "footnotes": footnotes,
        })
        messages.append(TurnNode.model_validate(raw))
    return messages


# ── Chat (ADR-019): pure-JSON `.sess` files ─────────────────────────────────
# `path` is excluded from the file's own JSON content and re-injected from
# the actual file location on load -- VaultNodeBase.path is a computed
# field, derived from where a file was found, never round-tripped through
# the file's own content (see schema_export._drop_path_from_required). The
# other excluded fields are API-response-only (app.py's _with_context_usage
# populates them fresh on every read) -- persisting them would just be
# stale data nothing ever re-derives on its own.
_CHAT_RESPONSE_ONLY_FIELDS = {
    "path", "context_tokens_used", "context_tokens_max", "excerpt_regenerating", "excerpt_summary_html",
}


def load_chat_session(path: Path) -> Chat:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Chat.model_validate({**raw, "path": path})


def save_chat_session(chat: Chat, path: Path) -> None:
    data = chat.model_dump(mode="json", exclude=_CHAT_RESPONSE_ONLY_FIELDS)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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
        default_sources: str = "Zotero Imported",
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
        # Same rationale as _chat_write_lock, for /sync/file's writes.
        self._path_write_lock = threading.Lock()

    def ensure_dirs(self) -> None:
        for d in self.default_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    # ── Internal traversal ────────────────────────────────────────────────────

    def iter_files(self, *, extensions: tuple[str, ...] = (".md",)) -> Iterator[Path]:
        """Walk the vault root once, yielding files whose name ends in one
        of *extensions*, skipping VCS/build directories and hidden dirs.
        This is the vault's only directory walk -- callers that need a
        different extension set (KG indexing, Chroma indexing) filter this
        same stream instead of re-walking the filesystem themselves."""
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
                if fname.endswith(extensions):
                    yield Path(dirpath) / fname

    def _find_md(self, slug: str) -> Path | None:
        """Find a .md file whose slug matches. Does NOT find .html files."""
        slug_norm = _file_slug(slug).lower()
        for path in self.iter_files():
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def _find_sess(self, slug: str) -> Path | None:
        """Find a chat .sess file whose slug matches. Only looks in the
        chats directory, not a full vault walk -- same convention
        find_stream_path already uses for streams (.yaml), unlike notes/
        sources, which the user can freely reorganise anywhere in the vault."""
        chats_dir = self.default_dirs[NodeType.chat]
        if not chats_dir.exists():
            return None
        slug_norm = _file_slug(slug).lower()
        for path in chats_dir.glob("*.sess"):
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def find_file(self, slug: str) -> Path | None:
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
        for path in self.iter_files(extensions=(".html",)):
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def node_type_from_frontmatter(self, fm: dict) -> NodeType:
        raw = fm.get("type", "note")
        try:
            return NodeType(raw)
        except ValueError:
            return NodeType.note

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_nodes(self, node_type: NodeType | None = None) -> VaultListing:
        buckets: dict[NodeType, list[VaultNodeMeta]] = {t: [] for t in NodeType}
        for path in self.iter_files():
            body = path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(body)
            nt = self.node_type_from_frontmatter(fm)
            if node_type and nt != node_type:
                continue
            if nt in (NodeType.stream, NodeType.chat):
                continue  # streams are .yaml, chats are .sess (ADR-019) -- neither is .md
            buckets[nt].append(self._meta_from_file(path, fm, content, nt))

        if not node_type or node_type == NodeType.stream:
            for s in self.list_streams():
                buckets[NodeType.stream].append(self._meta_from_stream(s))

        if not node_type or node_type == NodeType.chat:
            for c in self.list_chats():
                buckets[NodeType.chat].append(self._meta_from_chat(c))

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

    def list_chats(self) -> list[Chat]:
        chats_dir = self.default_dirs[NodeType.chat]
        if not chats_dir.exists():
            return []
        result = []
        for path in chats_dir.glob("*.sess"):
            try:
                result.append(load_chat_session(path))
            except Exception as exc:
                _log.warning("skipping unreadable chat %s: %s", path, exc)
        result.sort(key=lambda c: c.modified_at, reverse=True)
        return result

    def _meta_from_chat(self, c: Chat) -> VaultNodeMeta:
        return VaultNodeMeta(
            slug=c.slug, title=c.title, node_type=NodeType.chat, tags=c.tags, modified_at=c.modified_at,
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
            excerpt_of_chat=fm.get("excerpt_of_chat"),
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

    def create_source_from_citekey(
        self, citekey: str, title: str, body: str, *,
        zotero_key: str, authors: list[str], tags: list[str],
        year: int | None = None, doi: str | None = None, url: str | None = None,
    ) -> Source:
        """Create a source node from Zotero-derived metadata -- the
        vault-side half of POST /zotero/import/{key}."""
        self.ensure_dirs()
        slug = self.unique_slug(citekey)
        fm: dict = {
            "type": "source", "title": title, "citekey": citekey,
            "zotero_key": zotero_key, "authors": authors, "tags": tags,
        }
        if year:
            fm["year"] = year
        if doi:
            fm["doi"] = doi
        if url:
            fm["url"] = url
        path = self.default_dirs[NodeType.source] / f"{slug}.md"
        path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return self.get_source(slug)

    def get_chat(self, slug: str) -> Chat:
        path = self._find_sess(slug)
        if path is None:
            raise FileNotFoundError(f"chat not found: {slug!r}")
        return load_chat_session(path)

    def create_chat(self, title: str, model: str = "llama3") -> Chat:
        self.ensure_dirs()
        slug = self.unique_slug(title)
        path = self.default_dirs[NodeType.chat] / f"{slug}.sess"
        chat = Chat(slug=slug, title=title, tags=["chat"], model=model, path=path)
        save_chat_session(chat, path)
        return self.get_chat(slug)

    def save_chat(self, slug: str, messages: list[TurnNode], model: str | None = None) -> Chat:
        """`model`, when given, overwrites the chat's stored model — the
        model actually used for the turn just saved. Without this, a chat
        created before a model rename/merge (e.g. prisma-chat:7b ->
        qwen2.5:7b-32k) would keep displaying its original, now-stale name
        forever, even though every subsequent turn actually used the
        current config's model."""
        with self._chat_write_lock:
            path = self._find_sess(slug)
            if path is None:
                raise FileNotFoundError(f"chat not found: {slug!r}")
            chat = load_chat_session(path)
            update = {"messages": messages, "modified_at": datetime.utcnow()}
            if model is not None:
                update["model"] = model
            save_chat_session(chat.model_copy(update=update), path)
        return self.get_chat(slug)

    def append_messages(self, slug: str, new_messages: list[TurnNode], model: str | None = None) -> Chat:
        """Atomically append to whatever the chat's *current* on-disk
        messages are, not a snapshot taken before some earlier operation
        (e.g. an LLM call) started. `/chat`'s handler used to read
        `history` before calling the model, then write `history +
        [new turns]` once the call finished — if a `DELETE
        /chats/{slug}/messages/{index}` landed in between, that stale
        write would silently revive the just-deleted message. Reading and
        writing under the same lock closes that window."""
        with self._chat_write_lock:
            path = self._find_sess(slug)
            if path is None:
                raise FileNotFoundError(f"chat not found: {slug!r}")
            chat = load_chat_session(path)
            update = {"messages": chat.messages + new_messages, "modified_at": datetime.utcnow()}
            if model is not None:
                update["model"] = model
            save_chat_session(chat.model_copy(update=update), path)
        return self.get_chat(slug)

    def set_pinned_turns(self, chat_slug: str, indices: list[int]) -> Chat:
        """Write-only: records which turn indices are currently pinned.
        Does not regenerate the chat's single Excerpt note itself — that
        needs an LLM call (ADR-015's compressed-mode Summary), which this
        pure-storage layer has no access to. Callers (app.py) call this
        first, then assemble the new Summary and call save_excerpt()."""
        with self._chat_write_lock:
            path = self._find_sess(chat_slug)
            if path is None:
                raise FileNotFoundError(f"chat not found: {chat_slug!r}")
            chat = load_chat_session(path)
            save_chat_session(
                chat.model_copy(update={"pinned_turns": sorted(set(indices)), "modified_at": datetime.utcnow()}),
                path,
            )
        return self.get_chat(chat_slug)

    def save_excerpt(self, chat_slug: str, summary: str | None, raw_turns: list[TurnNode]) -> Note:
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
            note = self.create_note(f"Excerpt — {chat.title}", body=body, excerpt_of_chat=chat_slug)
            path = self._find_sess(chat_slug)
            save_chat_session(
                chat.model_copy(update={"excerpt_slug": note.slug, "modified_at": datetime.utcnow()}), path,
            )
            return note

    def get_any(self, slug: str) -> Note | Source | Chat | Stream:
        if self._find_sess(slug) is not None:
            # chats are stored as .sess, not .md (ADR-019) — find_file won't find them
            return self.get_chat(slug)
        path = self.find_file(slug)
        if path is None:
            # streams are stored as .yaml, not .md — find_file won't find them
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
            nt = self.node_type_from_frontmatter(html_fm)
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
        nt = self.node_type_from_frontmatter(fm)
        if nt == NodeType.source:
            return self.get_source(slug)
        if nt == NodeType.stream:
            return self.get_stream(slug)
        return self.get_note(slug)

    def slug_exists(self, slug: str) -> bool:
        return self.find_file(slug) is not None or self._find_sess(slug) is not None

    def body_of(self, slug: str) -> str | None:
        path = self.find_file(slug)
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
        path = self.find_file(slug)
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
        except Exception as exc:
            _log.warning("docu_craft render failed for %s, no .md companion generated: %s", html_path, exc)
            return False
        fm.setdefault("type", "note")
        companion.write_text(_render_frontmatter(fm) + md_content, encoding="utf-8")
        return True

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
        excerpt_of_chat: str | None = None,
    ) -> Note:
        self.ensure_dirs()
        slug = self.unique_slug(title)
        fm = {"type": "note", "title": title}
        if tags:
            fm["tags"] = tags
        if excerpt_of_chat:
            fm["excerpt_of_chat"] = excerpt_of_chat
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

    def unique_slug(self, title: str) -> str:
        """Slugify *title* and disambiguate against existing .md/.sess files
        by appending -1, -2, ... on collision."""
        base = _slugify(title)
        slug = base
        n = 1
        while self._find_md(slug) is not None or self._find_sess(slug) is not None:
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

    def find_stream_path(self, slug: str) -> Path | None:
        slug_norm = _file_slug(slug).lower()
        streams_dir = self.default_dirs[NodeType.stream]
        if not streams_dir.exists():
            return None
        for path in streams_dir.glob("*.yaml"):
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return None

    def get_stream(self, slug: str) -> Stream:
        path = self.find_stream_path(slug)
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
            except Exception as exc:
                _log.warning("skipping unreadable stream %s: %s", path, exc)
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
        path = self.find_stream_path(slug)
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
        path = self.find_stream_path(slug)
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
        chats_dir_name = self.default_dirs[NodeType.chat].name
        for entry in entries:
            name = entry.name
            if name in _SKIP_DIRS or name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=True) and directory == self.root and name == streams_dir_name:
                continue  # streams shown in the dedicated sidebar section, not the tree
            if entry.is_dir(follow_symlinks=True) and directory == self.root and name == chats_dir_name:
                continue  # chats shown in the dedicated sidebar section, not the tree
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
                except Exception as exc:
                    _log.warning("skipping unreadable stream %s in vault tree: %s", entry.path, exc)
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
                            html_nt = self.node_type_from_frontmatter(html_fm)
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
                        if fm.get("excerpt_of_chat"):
                            continue  # already shown in the chat's own Excerpt panel
                        nt = self.node_type_from_frontmatter(fm)
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
                except Exception as exc:
                    _log.warning("skipping unreadable file %s in vault tree: %s", entry.path, exc)
        return nodes

    # ── Node operations ───────────────────────────────────────────────────────

    def move_node(self, slug: str, dest_dir: str) -> str:
        path = self.find_file(slug)
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
        sess_path = self._find_sess(slug)
        if sess_path is not None:
            new_stem = _slugify(new_title)
            new_path = sess_path.parent / f"{new_stem}.sess"
            if new_path.exists() and new_path != sess_path:
                raise FileExistsError(f"a file named {new_stem!r} already exists")
            chat = load_chat_session(sess_path)
            new_slug = _file_slug(new_stem)
            sess_path.rename(new_path)
            save_chat_session(
                chat.model_copy(update={"title": new_title, "slug": new_slug, "modified_at": datetime.utcnow()}),
                new_path,
            )
            return new_slug
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
        path = self.find_file(slug) or self._find_sess(slug)
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

    # ── Path-based access (sync) ─────────────────────────────────────────────
    # Used by /sync/* — unlike the rest of this class, the desktop client
    # addresses files by their vault-relative path directly (it mirrors the
    # vault's on-disk layout 1:1), not by slug. Kept narrow (explicit
    # per-directory content types) rather than extending the slug-resolution
    # machinery or accepting any extension anywhere in the vault.
    #
    # streams/ is the one other directory with real, user-created vault
    # content that isn't .md (see create_stream/save_stream above — stored
    # as .yaml). It's the opposite case from .vault-files/ (internal app
    # state, excluded entirely via the leading-dot rule): this is a content
    # dir with its own known type, not something to hide from sync.

    def resolve_within_root(self, rel_path: str) -> Path:
        """Resolve `rel_path` against the vault root, rejecting traversal and
        reserved/hidden directories. The one shared vault-containment check —
        previously `/vault/assets/{path}` (app.py's `vault_asset`) had its own,
        independently-implemented `os.path.abspath` + string-prefix version
        that (unlike this one) didn't reject paths under `.git/`/`.vault-files/`
        etc., only staying safe in practice because no allowed asset extension
        was expected to live there. Both callers should go through this single
        implementation now."""
        p = Path(rel_path)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("path outside vault")
        if any(part in _SKIP_DIRS or part.startswith(".") for part in p.parts[:-1]):
            raise ValueError("path inside a reserved or hidden directory")
        candidate = self.root / p
        # A directory *inside* the vault that is itself a symlink pointing
        # outside it (e.g. vault/notes/escape -> /etc) would sail through
        # the string-based checks above, which only look at the literal
        # path components, not what a symlink in the middle of the path
        # actually resolves to. .resolve() is safe to call even when
        # `candidate` doesn't exist yet (new-file writes) -- it only
        # resolves symlinks in the parts that do exist.
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("path escapes vault root via a symlink")
        return candidate

    def _safe_sync_path(self, rel_path: str) -> Path:
        path = self.resolve_within_root(rel_path)
        p = Path(rel_path)
        is_stream_yaml = p.parts[0] == "streams" and rel_path.endswith(".yaml")
        if not (rel_path.endswith(".md") or is_stream_yaml):
            raise ValueError("sync only supports .md files, or .yaml files under streams/")
        return path

    def read_by_path(self, rel_path: str) -> tuple[str, float] | None:
        path = self._safe_sync_path(rel_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8"), path.stat().st_mtime

    def write_by_path(self, rel_path: str, body: str) -> float:
        """Create-or-overwrite. Returns the new mtime."""
        path = self._safe_sync_path(rel_path)
        with self._path_write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            return path.stat().st_mtime

    def delete_by_path(self, rel_path: str) -> None:
        path = self._safe_sync_path(rel_path)
        with self._path_write_lock:
            path.unlink(missing_ok=True)

    def list_md_manifest(self) -> list[tuple[str, float, int]]:
        """(rel_path, mtime, size) for every synced file — every .md file
        plus every streams/*.yaml — the desktop client's input for
        initial-reconciliation diffing. See _safe_sync_path for why streams/
        gets this one exception."""
        manifest = []
        for path in self.iter_files():
            stat = path.stat()
            manifest.append((path.relative_to(self.root).as_posix(), stat.st_mtime, stat.st_size))
        streams_dir = self.default_dirs[NodeType.stream]
        if streams_dir.exists():
            for path in streams_dir.glob("*.yaml"):
                stat = path.stat()
                manifest.append((path.relative_to(self.root).as_posix(), stat.st_mtime, stat.st_size))
        return manifest

    def delete_stream(self, slug: str) -> None:
        path = self.find_stream_path(slug)
        if path is None:
            raise FileNotFoundError(f"stream not found: {slug!r}")
        path.unlink()
