from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator

import yaml

from prisma.schema_gov import ContentFormat, RichContent
from prisma.storage.models.vault_models import (
    Chat, ChatRole, Note, NodeType, Source, SourceKind, SourceOrigin, Stream, StreamStatus,
    RefreshFrequency, TurnNode, VaultListing, VaultNodeMeta, VaultTreeNode,
    _migrate_message_v1_to_v2,
)

_log = logging.getLogger("prisma.vault")

# Recognised companion file extensions stored alongside a .md source node.
# .jpg/.jpeg added alongside .tex/.drawio for attachment promotion (v3,
# POST /chats/{slug}/attachments/promote) -- previously absent even though
# _ALLOWED_ASSET_EXTS (app.py's GET /vault/assets/) already served jpg fine;
# nothing had ever created a jpg companion before, so the gap went unnoticed.
COMPANION_EXTS = (".pdf", ".html", ".htm", ".svg", ".epub", ".docx", ".tex", ".drawio", ".jpg", ".jpeg")


def pdf_bytes_to_md(data: bytes) -> str:
    """Relocated from zotero_routes.py (was `_pdf_bytes_to_md`) -- a pure
    function of raw bytes, no Zotero dependency, so it belongs at the
    service layer where both zotero_import() and ensure_md_format() (the
    generic companion->.md conversion, see below) can share it, rather than
    ensure_md_format() reaching into a route module for it. Closes the gap
    documented in TODO.md: a manually-attached PDF companion (no Zotero
    import involved) previously got no body text at all."""
    try:
        from docu_craft.renderers.pdf_md import pdf_to_md
        return pdf_to_md(data)
    except Exception as exc:
        _log.warning("pdf_to_md conversion failed, no body generated: %s", exc)
        return ""

# Directories that are never part of the vault (VCS, build artifacts, hidden).
# Internal app state (chromadb/, kg-out/) lives under .vault-files/ instead of
# being listed here by name — the leading-dot rule below already excludes it,
# the same way .git is excluded, so a new internal dir never needs a new entry.
_SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


# Most Linux filesystems (ext4 etc.) cap a single path component at 255
# bytes. A slug is always pure ASCII (the regex below strips everything
# outside [a-z0-9] to a single hyphen, so non-ASCII input collapses rather
# than expanding), so 200 characters leaves real headroom for a
# disambiguation suffix (unique_slug()'s "-1", "-2", ...) and an extension
# (".md") without ever approaching that limit. An all-ASCII single-word
# title as short as ~300 characters (nowhere near an intuitively "absurd"
# length) raises OSError("File name too long") from path.write_text()
# without this cap -- affects every _slugify() caller (create_note
# included), not just whichever one happens to get noticed first.
_MAX_SLUG_LENGTH = 200


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-") or "untitled"
    return slug[:_MAX_SLUG_LENGTH].rstrip("-") or "untitled"


def _file_slug(stem: str) -> str:
    """Turn a filesystem stem into a URL-safe slug, preserving case."""
    slug = re.sub(r"[^a-zA-Z0-9\-_\.]", "-", stem)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "untitled"


# frontmatter_for_relpath() reads only this many bytes -- a frontmatter
# block larger than this is malformed, and its year lookup degrades to None.
_FRONTMATTER_READ_BYTES = 8192

# citekey_exists() needs different handling than the fixed bound above:
# that one is fine to silently degrade on overflow (a best-effort year
# lookup), but a truncated read here means _parse_frontmatter can't find
# the closing '---' at all and returns {} -- a false "citekey not in use"
# that lets create_source_from_citekey_if_free() create a real collision
# despite its own lock. A fixed bound here, however large, is only ever a
# guess against how big a Source's frontmatter can get -- and this same
# module's own SourceCreateRequest field caps (authors/tags list length x
# per-item length) set that ceiling, not this constant. A prior fixed
# 65536-byte bound was comfortably outgrown the moment those caps allowed
# a large-enough author list (confirmed: ~100KB for 200 authors x 512
# chars, both within the documented per-field caps), silently reopening
# the exact collision this scan exists to prevent. So citekey_exists()
# below reads incrementally instead, starting at this size and growing
# only for the files that genuinely need it -- the normal case (frontmatter
# fits in the first chunk) pays no extra cost. _CITEKEY_SCAN_MAX_BYTES is
# a hard ceiling purely to stop an unbounded read against a malformed file
# with no closing '---' at all, not a bound this scan is meant to rely on
# for real Source files.
_CITEKEY_SCAN_READ_BYTES = 65536
_CITEKEY_SCAN_MAX_BYTES = 4 * 1024 * 1024


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


def _enum_from_frontmatter(fm: dict, key: str, enum_cls, default):
    """Shared by _source_origin_from_frontmatter()/_source_kind_from_
    frontmatter() below -- same defensive-fallback shape as VaultService.
    node_type_from_frontmatter(): an unrecognized/legacy/forward-
    incompatible enum value (hand-edited file, or a newer app version's
    future enum member) must not crash GET /notes/{slug} for that one
    node, it should just fall back to `default`."""
    try:
        return enum_cls(fm.get(key) or default.value)
    except ValueError:
        return default


def _source_origin_from_frontmatter(fm: dict) -> SourceOrigin:
    return _enum_from_frontmatter(fm, "origin", SourceOrigin, SourceOrigin.zotero)


def _source_kind_from_frontmatter(fm: dict) -> SourceKind:
    return _enum_from_frontmatter(fm, "source_kind", SourceKind, SourceKind.paper)


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


def _resolve_system_prompts(pool: list[str], messages: list[TurnNode]) -> tuple[list[str], list[TurnNode]]:
    """Dedupes each message's transient `system_prompt_text` (set fresh by
    ChatAgent.respond(), excluded from the persisted .sess -- see
    TurnNode.system_prompt_index's field comment) against `pool`, extending
    it with any text not already present, and returns messages with
    `system_prompt_index` resolved to point at the right pool entry. A
    message with no `system_prompt_text` (a user turn, or an
    already-persisted assistant turn loaded back from disk --
    `system_prompt_text` never round-trips through a save/load cycle)
    passes through with its existing `system_prompt_index` untouched.
    Recurses into `alternates` -- a regenerated turn's fresh attempt can
    carry its own new text even though the demoted previous attempt it
    displaces into `alternates` is already resolved."""
    pool = list(pool)

    def resolve_one(m: TurnNode) -> TurnNode:
        update: dict = {}
        if m.system_prompt_text is not None:
            try:
                idx = pool.index(m.system_prompt_text)
            except ValueError:
                pool.append(m.system_prompt_text)
                idx = len(pool) - 1
            update["system_prompt_index"] = idx
        if m.alternates:
            update["alternates"] = [resolve_one(a) for a in m.alternates]
        return m.model_copy(update=update) if update else m

    return pool, [resolve_one(m) for m in messages]


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
        # Same rationale again, for the manual-create route's citekey-
        # uniqueness check-then-write (see create_source_from_citekey_if_free).
        self._source_write_lock = threading.Lock()

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

    def slug_for_relpath(self, rel_path: str | Path) -> str:
        """Encode a path relative to the vault root as the `dir--name`
        compound slug (ADR-021) that `_resolve_compound_slug`/`_find_md`
        below decode -- kept beside its decode counterpart so the two
        can't drift apart."""
        return str(Path(rel_path).with_suffix("")).replace("/", "--").replace("\\", "--")

    def frontmatter_for_relpath(self, rel_path: str | Path) -> dict:
        """Frontmatter of a vault file addressed by its already-known
        vault-relative path -- skips the slug decode and full-vault walk
        `get_any()` does, and reads only the file's head. For hot paths that
        already hold the relative path (e.g. kg_queries.timeline)."""
        try:
            candidate = (self.root / Path(rel_path)).resolve()
            if not candidate.is_relative_to(self.root.resolve()):
                return {}
            with candidate.open("r", encoding="utf-8", errors="replace") as f:
                head = f.read(_FRONTMATTER_READ_BYTES)
        except OSError:
            return {}
        fm, _ = _parse_frontmatter(head)
        return fm

    def _resolve_compound_slug(self, slug: str, suffix: str) -> Path | None:
        """Decode a `dir--name` compound slug (ADR-021) into a candidate
        path with the given suffix, refusing to resolve outside the vault
        root. Without this check, a slug like `"..--..--etc--passwd"`
        decodes (via `.replace("--", "/")`) to a `..`-laden relative path
        that escapes the vault root once resolved, and a slug beginning
        with `--` decodes to a leading `/` -- `Path`'s own `/` operator
        discards the left operand entirely when the right side is absolute,
        so `self.root / "/etc/passwd"` silently becomes `Path("/etc/passwd")`.
        READ_SOURCE and `GET /notes/{slug}/read` pass a slug straight
        through to this decode with no other validation in between, unlike
        the wiki-link resolution path this decode was originally written
        for."""
        if "--" not in slug:
            return None
        try:
            # Append, not .with_suffix(): a decoded stem can contain dots
            # (`paper.v1`), which .with_suffix() would rewrite.
            candidate = self.root / (slug.replace("--", "/") + suffix)
            resolved = candidate.resolve()
            root_resolved = self.root.resolve()
        except (OSError, ValueError):  # e.g. embedded NUL — Path rejects it
            return None
        if not resolved.is_relative_to(root_resolved):
            return None
        # is_file(), not exists(): a directory literally named `foo.md`
        # would otherwise be handed back and open()ed by read_source().
        return candidate if candidate.is_file() else None

    def _find_md(self, slug: str) -> Path | None:
        """Find a .md file whose slug matches -- either the bare stem, or a
        dir--name compound slug encoding its folder (ADR-021; the same
        encoding move_node() produces). Does NOT find .html files.

        This is the single source of truth for .md resolution -- get_source()/
        get_note() call this directly rather than find_file(), so the
        compound-slug decode has to live here, not just in find_file()
        (found live: it used to live only in find_file(), which get_any()
        calls once to sniff node_type and then discards, re-resolving via
        get_source()/get_note() -> this method, silently missing the decode)."""
        slug_norm = _file_slug(slug).lower()
        for path in self.iter_files():
            if _file_slug(path.stem).lower() == slug_norm:
                return path
        return self._resolve_compound_slug(slug, ".md")

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
        """Find a .md or .html file whose slug matches. _find_md() already
        covers the .md-including-compound-slug case; the .html compound
        decode still needs to live here since there's no dedicated
        _find_html() equivalent."""
        md = self._find_md(slug)
        if md is not None:
            return md
        # Path-relative slugs encode '/' as '--' (e.g. "papers--bricken2003--index")
        html_candidate = self._resolve_compound_slug(slug, ".html")
        if html_candidate is not None:
            return html_candidate
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
            # Same companion detection get_source() already does -- a Note
            # can have a real companion too (manually dropped, or written by
            # POST /chats/{slug}/attachments/promote), and GET /notes/{slug}
            # /original needs this to know it's there. Previously never set
            # for notes, only sources -- found while building attachment
            # promotion, whose whole point is a servable companion file.
            original_ext=_companion_ext(path),
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
            journal=fm.get("journal"),
            volume=fm.get("volume"),
            issue=fm.get("issue"),
            pages=fm.get("pages"),
            publisher=fm.get("publisher"),
            url=fm.get("url"),
            item_type=fm.get("item_type"),
            origin=_source_origin_from_frontmatter(fm),
            source_kind=_source_kind_from_frontmatter(fm),
        )

    def create_source_from_citekey(
        self, citekey: str, title: str, body: str, *,
        zotero_key: str | None = None,
        origin: SourceOrigin = SourceOrigin.zotero,
        source_kind: SourceKind = SourceKind.paper,
        authors: list[str], tags: list[str],
        year: int | None = None, doi: str | None = None, url: str | None = None,
        journal: str | None = None, volume: str | None = None, issue: str | None = None,
        pages: str | None = None, publisher: str | None = None, item_type: str | None = None,
    ) -> Source:
        """Create a source node -- the vault-side half of both
        POST /zotero/import/{key} (zotero_key set, origin defaults to
        zotero) and the manual-create route (zotero_key=None, origin=
        upload). No citekey-uniqueness enforcement here -- see
        create_source_from_citekey_if_free() for that, used by the manual-
        create route; Zotero import doesn't currently go through it."""
        self.ensure_dirs()
        slug = self.unique_slug(citekey)
        fm: dict = {
            "type": "source", "title": title, "citekey": citekey,
            "authors": authors, "tags": tags, "origin": origin.value,
        }
        if zotero_key:
            fm["zotero_key"] = zotero_key
        if source_kind != SourceKind.paper:
            fm["source_kind"] = source_kind.value
        # is not None, not truthy -- year=0 is a real (if unrealistic)
        # value, and this must agree with update_source_bibliographic_
        # fields()'s handling of the same field or POST /notes/sources and
        # PATCH /{slug}/source disagree on whether year=0 sticks.
        if year is not None:
            fm["year"] = year
        if doi:
            fm["doi"] = doi
        if url:
            fm["url"] = url
        if journal:
            fm["journal"] = journal
        if volume:
            fm["volume"] = volume
        if issue:
            fm["issue"] = issue
        if pages:
            fm["pages"] = pages
        if publisher:
            fm["publisher"] = publisher
        if item_type:
            fm["item_type"] = item_type
        path = self.default_dirs[NodeType.source] / f"{slug}.md"
        path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return self.get_source(slug)

    def update_source_bibliographic_fields(
        self, slug: str, *, title: str | None = None, authors: list[str] | None = None,
        year: int | None = None, doi: str | None = None, tags: list[str] | None = None,
        source_kind: SourceKind | None = None,
        journal: str | None = None, volume: str | None = None,
        issue: str | None = None, pages: str | None = None, publisher: str | None = None,
        url: str | None = None, item_type: str | None = None,
    ) -> Source:
        """Merges the given fields into `slug`'s existing frontmatter,
        leaving the body and every other field untouched.

        Two different "was this given" rules for two different groups of
        callers, deliberately:
        - journal/volume/issue/pages/publisher/url/item_type: the original
          ADR-020 backfill command's write path, for sources imported
          before these fields existed on Source. Uses a *truthy* check
          (`if value:`) so re-running backfill against a partially-filled
          source never blanks a field just because Zotero returned an
          empty string for it this time -- source_backfill.py depends on
          this exact behavior (see test_does_not_blank_out_fields_when_
          called_with_none), not changed here.
        - title/authors/year/doi/tags/source_kind: added for the manual
          edit-metadata route. Uses `is not None` instead -- an explicit
          `authors: []` from that route means "clear the authors," a real,
          expected edit action; a truthy check would silently no-op it.
          Omitting the field (Pydantic default None) still means "leave it
          alone" either way, so this doesn't regress the "don't touch what
          wasn't given" guarantee, it just makes an explicit empty value
          actually take effect for the fields where that's a meaningful
          edit. source_kind has no meaningful "empty" value (it's an enum,
          not a string/list) but is grouped here anyway since it's the
          same "settable after creation" capability the others gained.
          `year` is the one exception within this group: unlike authors/
          tags/doi, there is no value distinct from "omitted" that means
          "clear this" for a plain `int | None` -- sending `year: null`
          is indistinguishable from not sending `year` at all, so a year
          can be set or changed but never cleared back to unset through
          this method, same practical limitation as the truthy-checked
          group below (grouped with them in the UI's edit-metadata hint
          for that reason), just for a different underlying cause.

        Deliberately excludes `citekey`: renderer.py's citation index
        resolves [[@citekey]] against current frontmatter values, so
        changing it after creation would silently orphan or misdirect any
        citation already pointing at this source elsewhere in the vault.

        Holds _source_write_lock across the whole read-merge-write, same as
        attach_source_companion() below -- without it, a metadata edit
        racing a companion upload's own read-merge-write of the identical
        frontmatter (the two are read-merge-write on the same file, not
        independent) is a lost-update: whichever finishes last silently
        wins, discarding the other caller's already-200'd change with no
        error to either side."""
        with self._source_write_lock:
            path = self._find_md(slug)
            if path is None:
                raise FileNotFoundError(f"source not found: {slug!r}")
            raw = path.read_text(encoding="utf-8")
            fm, content = _parse_frontmatter(raw)
            for key, value in [("title", title), ("authors", authors), ("year", year), ("doi", doi), ("tags", tags)]:
                if value is not None:
                    fm[key] = value
            if source_kind is not None:
                fm["source_kind"] = source_kind.value
            for key, value in [
                ("journal", journal), ("volume", volume), ("issue", issue),
                ("pages", pages), ("publisher", publisher), ("url", url), ("item_type", item_type),
            ]:
                if value:
                    fm[key] = value
            path.write_text(_render_frontmatter(fm) + content, encoding="utf-8")
            return self.get_source(slug)

    def citekey_exists(self, citekey: str) -> bool:
        """Scans current vault files' frontmatter for a matching citekey --
        used by the manual-create route's collision guard, since (unlike a
        Zotero key) a hand-entered citekey has no external uniqueness
        guarantee. A few lines of overlap with renderer.py's
        _build_citekey_index() (same frontmatter scan) is cheaper than
        reaching into that module's private, differently-shaped internals
        (it builds a citekey->slug index for citation *resolution*; this is
        a plain existence check) just to avoid the duplication.

        Reads only each file's head, not the whole file -- this runs inside
        create_source_from_citekey_if_free()'s lock, so a full-body read
        per file (a Source's body can be a full PDF-extracted paper, tens
        of KB+) would serialize every manual create behind a scan whose
        cost scales with total vault content size, not just file count.
        Starts at _CITEKEY_SCAN_READ_BYTES and grows only if that wasn't
        enough to find the closing '---' -- see that constant's own
        comment for why a single fixed bound, however large, can't stay
        correct here. frontmatter_for_relpath()'s _FRONTMATTER_READ_BYTES
        is fine to silently degrade on overflow (a best-effort lookup);
        a truncated read here would falsely report an in-use citekey as
        free, letting a real collision through despite the lock.

        Reads in binary mode, not text mode -- opening with encoding="utf-8"
        would make f.read(N) read N *characters*, not N bytes, so
        non-ASCII-heavy frontmatter (e.g. non-Latin author names) could
        consume up to 4x the intended bytes per read, weakening
        _CITEKEY_SCAN_MAX_BYTES's own hard-ceiling guarantee by the same
        factor. Decoded once at the end, not per growth iteration, so the
        loop itself stays cheap."""
        for path in self.iter_files():
            try:
                with path.open("rb") as f:
                    head_bytes = f.read(_CITEKEY_SCAN_READ_BYTES)
                    while (
                        head_bytes.startswith(b"---")
                        and head_bytes.find(b"\n---", 3) == -1
                        and len(head_bytes) < _CITEKEY_SCAN_MAX_BYTES
                    ):
                        more = f.read(_CITEKEY_SCAN_READ_BYTES)
                        if not more:
                            break
                        head_bytes += more
            except OSError:
                # A file can vanish between iter_files()'s walk yielding it
                # and this read (a concurrent delete/move) -- harmless to
                # this existence check either way, so skip it rather than
                # letting POST /notes/sources 500 on an unrelated race.
                continue
            fm, _ = _parse_frontmatter(head_bytes.decode("utf-8", errors="replace"))
            if fm.get("citekey") == citekey:
                return True
        return False

    def create_source_from_citekey_if_free(self, citekey: str, title: str, body: str, **kwargs) -> Source:
        """Atomic check-and-create: holds _source_write_lock across the
        citekey_exists() check and the actual write. Calling those two as
        separate steps from the route layer (check, then create) leaves a
        real TOCTOU window -- two concurrent manual-create requests (a
        double-submit, or two auto-generated citekeys landing on the same
        author+year) can both see "free" before either has written, and
        both create a Source with the same citekey. renderer.py's
        _build_citekey_index() then resolves [[@citekey]] to whichever one
        it scans last -- the other becomes silently unreachable by
        citation, with no error to either creator. Raises ValueError (not
        FileExistsError) on collision to match this module's other
        caller-facing validation errors (see attach_source_companion).

        Not used by Zotero import -- that path has its own, separate
        citekey-collision behavior via unique_slug() on the *file slug*
        (not the citekey field itself), unchanged here; folding it into
        this same guard would change POST /zotero/import/{key}'s existing
        behavior, out of scope for the manual-create gap this exists to
        close."""
        with self._source_write_lock:
            if self.citekey_exists(citekey):
                raise ValueError(f"citekey already in use: {citekey!r}")
            return self.create_source_from_citekey(citekey, title, body, **kwargs)

    def attach_source_companion(self, slug: str, filename: str, data: bytes) -> Source:
        """Attach or replace `slug`'s companion file from raw bytes -- the
        manual-upload counterpart to what Zotero import's pdf_bytes_to_md()
        path does automatically. Regenerates the sibling .md body via
        ensure_md_format(force=True) for pdf/html/htm companions only,
        matching generate_md_format() route's own extension restriction;
        other companion kinds are a no-op body-wise (image OCR/extraction
        is a tracked, separate gap -- not attempted here).

        Passes force=True to ensure_md_format() only when *replacing* an
        existing companion, not on a first attachment -- the whole point of
        re-uploading is to refresh stale extracted text, so the empty-
        body-only gate would otherwise keep serving the first upload's
        extraction forever after every subsequent replace. A first
        attachment still goes through with the default force=False,
        protecting a genuinely hand-typed body (or one synthesized at
        Zotero-import time from the abstract when no PDF was available)
        from being silently overwritten the moment any companion is
        attached. A failed new extraction still leaves the old body
        untouched either way -- ensure_md_format() returns before writing
        whenever conversion produces nothing, force or not.

        Skips the write and re-extraction entirely when the uploaded bytes
        are byte-identical to the existing companion -- a retried/duplicate
        upload of the same file would otherwise still pay for a full
        re-extraction (a real cost for a large PDF) for a change that
        didn't actually happen. The calling route still marks the vault
        stale and broadcasts a vault_change regardless (this method has no
        way to tell it not to) -- a smaller, separate waste than the
        extraction this actually avoids, not chased further here.

        Holds _source_write_lock across the entire method, including the
        (possibly seconds-long) ensure_md_format() extraction -- three
        separate races otherwise open up, none needing true byte-level bad
        luck to hit, just two requests landing close together (double-
        submit, two tabs, a client retry racing the original):
        - find_companion() read + the later write are two separate steps;
          two concurrent first-time uploads (no existing companion) can
          both see existing=None and both persist a companion, permanently
          orphaning whichever one COMPANION_EXTS's fixed scan order doesn't
          resolve to first.
        - the same TOCTOU lets two concurrent *replacing* uploads both
          capture the same stale `existing` and both call existing.unlink()
          on it -- the second raises FileNotFoundError, which the calling
          route mislabels as 404 "source not found" for an upload that
          actually succeeded.
        - ensure_md_format() reads this exact file's frontmatter into its
          own `fm` before extraction starts; a concurrent metadata PATCH
          (update_source_bibliographic_fields(), which takes this same
          lock) completing in between would otherwise get silently
          overwritten by ensure_md_format()'s stale-frontmatter write when
          the slow extraction finally finishes, discarding an edit that
          already returned 200 to its caller.

        Trade-off worth naming: _source_write_lock is global, not per-slug,
        so this also blocks create_source_from_citekey_if_free() and
        update_source_bibliographic_fields() for *unrelated* sources for
        the full extraction duration, not just this one's. Correct beats
        fast here -- see TODO.md's Vault section for the per-slug-lock
        follow-up that would remove this cost."""
        with self._source_write_lock:
            path = self._find_md(slug)
            if path is None:
                raise FileNotFoundError(f"source not found: {slug!r}")
            ext = Path(filename).suffix.lower()
            if ext not in COMPANION_EXTS:
                raise ValueError(f"unsupported companion extension: {ext!r}")
            existing = self.find_companion(slug)
            if (
                existing is not None
                and existing.suffix == ext
                and existing.stat().st_size == len(data)
                and existing.read_bytes() == data
            ):
                return self.get_source(slug)
            # force=True only when *replacing an extraction-relevant
            # companion* -- not just "any prior companion existed". A prior
            # .jpg/.svg/etc. never ran extraction at all, so a first-ever
            # .pdf/.html attach after one of those is still a first
            # extraction, not a refresh: checking existing is not None
            # alone would call this a "replace" and force through the
            # empty-body-only gate, clobbering a genuinely hand-typed body
            # (a manually created Source's own prose, or a Zotero-import
            # body synthesized from the abstract when no PDF was available)
            # on what is actually its first real extraction.
            is_replace = existing is not None and existing.suffix in (".pdf", ".html", ".htm")
            companion_path = path.with_suffix(ext)
            # Write to a temp file and atomically replace, rather than
            # writing companion_path directly -- when ext matches the
            # existing companion's extension, companion_path IS that
            # existing file, and opening it "wb" truncates it immediately,
            # before the write can even fail. A write failure partway
            # through (disk full, permission error, killed mid-write) then
            # left the original destroyed, not untouched. Path.replace() is
            # atomic on the same filesystem, so this either fully succeeds
            # or leaves the original companion exactly as it was.
            # uuid4-suffixed, not just "<name>.upload.tmp" -- belt-and-
            # suspenders alongside the lock above: two tmp writes still
            # can't collide even if this method is ever called without it.
            tmp_path = companion_path.with_name(f"{companion_path.name}.{uuid.uuid4().hex}.upload.tmp")
            try:
                tmp_path.write_bytes(data)
                tmp_path.replace(companion_path)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
            # Unlink the stale, different-extension companion only AFTER
            # the new one is safely on disk -- unlinking first meant a
            # write failure in between left the Source with no companion at
            # all instead of the original, untouched one. missing_ok=True
            # as the same belt-and-suspenders: harmless if the lock above
            # already makes this impossible, cheap insurance if it's ever
            # removed.
            if existing is not None and existing.suffix != ext:
                existing.unlink(missing_ok=True)
            if ext in (".pdf", ".html", ".htm"):
                self.ensure_md_format(companion_path, force=is_replace)
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
            pool, resolved_messages = _resolve_system_prompts(chat.system_prompts, messages)
            update = {"messages": resolved_messages, "system_prompts": pool, "modified_at": datetime.utcnow()}
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
            pool, resolved_new = _resolve_system_prompts(chat.system_prompts, new_messages)
            update = {"messages": chat.messages + resolved_new, "system_prompts": pool, "modified_at": datetime.utcnow()}
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

    def ensure_md_format(self, companion_path: Path, force: bool = False) -> bool:
        """Convert a companion file (.html or .pdf) to Markdown and store it
        in the sibling .md body. Returns True if the companion .md was
        created/updated, False if already present. .pdf uses pdf_bytes_to_md
        (module-level, above) -- the same conversion zotero_import() uses,
        generalized here so a manually-attached PDF (no Zotero import
        involved) gets real extracted text too, not just whatever metadata
        the user typed by hand. See TODO.md's now-closed PDF->MD gap.

        `force`: skip the "only fill an empty body" gate below. Default
        False protects a hand-edited note from being clobbered by a
        redundant call (the existing /notes/{slug}/md route's use case).
        `attach_source_companion()` passes force=True when *replacing* an
        existing companion -- the whole point of re-uploading is to
        refresh stale content, so the empty-body gate would otherwise
        silently keep serving the old extraction forever."""
        companion = companion_path.with_suffix(".md")
        if companion.exists():
            raw = companion.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(raw)
            if body.strip() and not force:
                return False
        else:
            fm, body = {"title": companion_path.stem}, ""
        if companion_path.suffix == ".pdf":
            md_content = pdf_bytes_to_md(companion_path.read_bytes())
            if not md_content:
                return False
        else:
            try:
                from docu_craft import render as _dc_render
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
                    tmp = Path(tf.name)
                try:
                    _dc_render(source=companion_path, format="md", output=tmp)
                    md_content = tmp.read_text(encoding="utf-8")
                finally:
                    # Must run even when _dc_render()/read_text() raises --
                    # the file already exists on disk from NamedTemporaryFile
                    # above regardless of what happens next. Previously only
                    # unlinked on the success path, leaking one temp file per
                    # failed conversion -- attach_source_companion()'s
                    # force=True re-extraction on every companion re-upload
                    # means a retried failing upload now leaks one per retry,
                    # not just once.
                    tmp.unlink(missing_ok=True)
            except Exception as exc:
                _log.warning("docu_craft render failed for %s, no .md companion generated: %s", companion_path, exc)
                return False
        fm.setdefault("type", "note")
        # Atomic tmp-file+replace, not a direct write_text() -- same
        # reasoning attach_source_companion() already applies to the
        # companion *binary*: a plain write_text() opens in "w" (truncating
        # immediately), so a failure partway through (disk full, killed
        # mid-write) would destroy whatever body this Source already had
        # instead of leaving it untouched. This path runs right after this
        # same method's own (possibly seconds-long) extraction above, and
        # attach_source_companion()'s force=True re-upload flow now drives
        # it far more often than before this PR -- worth the same
        # protection its sibling write already has, not just the binary.
        tmp_path = companion.with_name(f"{companion.name}.{uuid.uuid4().hex}.mdformat.tmp")
        try:
            tmp_path.write_text(_render_frontmatter(fm) + md_content, encoding="utf-8")
            tmp_path.replace(companion)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
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
                            html_slug = self.slug_for_relpath(rel)
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

    def move_node(self, slug: str, dest_dir: str) -> tuple[str, str, str]:
        """Returns (new_slug, old_rel_path, new_rel_path). The two rel paths
        are for the caller (app.py's route) to broadcast a vault_change over
        WS -- without that, a connected desktop client's local sync mirror
        never learns the old path is gone, and can end up pushing its still-
        present stale copy back up as a "new" file, duplicating the move."""
        path = self.find_file(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        old_rel = str(path.relative_to(self.root))
        dest = self.resolve_within_root(dest_dir)
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
        new_slug = self.slug_for_relpath(rel)
        return new_slug, old_rel, str(rel)

    def rename_node(self, slug: str, new_title: str) -> tuple[str, str | None, str | None]:
        """Returns (new_slug, old_rel_path, new_rel_path) -- the last two are
        None for a chat (.sess isn't part of the sync protocol at all, see
        _safe_sync_path, so there's nothing to broadcast); see move_node's
        docstring for why the caller needs these for a .md rename."""
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
            return new_slug, None, None
        path = self._find_md(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        old_rel = str(path.relative_to(self.root))
        new_stem = _slugify(new_title)
        new_path = path.parent / f"{new_stem}.md"
        if new_path.exists() and new_path != path:
            raise FileExistsError(f"a file named {new_stem!r} already exists")
        raw = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(raw)
        fm["title"] = new_title
        path.rename(new_path)
        new_path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
        return _file_slug(new_stem), old_rel, str(new_path.relative_to(self.root))

    def delete_node(self, slug: str) -> str | None:
        """Returns the deleted file's vault-relative path, or None for a
        chat (.sess isn't part of the sync protocol, see move_node's
        docstring for why the caller needs this for a synced file)."""
        path = self.find_file(slug) or self._find_sess(slug)
        if path is None:
            raise FileNotFoundError(f"node not found: {slug!r}")
        is_synced = path.suffix != ".sess"
        rel = str(path.relative_to(self.root)) if is_synced else None
        path.unlink()
        companion = path.with_suffix(".md") if path.suffix == ".html" else None
        if companion and companion.exists():
            companion.unlink()
        return rel

    def create_dir(self, rel_path: str) -> None:
        self.resolve_within_root(rel_path).mkdir(parents=True, exist_ok=True)

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
