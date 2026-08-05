"""One-time migration: vault/chats/*.md (markdown transcript + embedded
`prisma:meta` JSON comment) -> vault/chats/*.sess (pure JSON, ADR-019).

Reads via the existing markdown parse path (_parse_frontmatter/
_parse_chat_body) read-only, purely for this conversion -- those functions
stay in vault.py unchanged, still serving the not-yet-cut-over Chat/
ChatMessage API path, until the API/frontend wiring phase replaces them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prisma.schema_gov import ContentFormat, RichContent
from prisma.services.vault import VaultService, _file_slug, _parse_chat_body, _parse_frontmatter, save_chat_session
from prisma.storage.models.vault_models import ChatSession, NodeType, SessionMessage


@dataclass
class ChatMigrationResult:
    slug: str
    md_path: Path
    sess_path: Path
    message_count: int
    error: str | None = None


def _convert_one(md_path: Path) -> ChatSession:
    body = md_path.read_text(encoding="utf-8")
    fm, content = _parse_frontmatter(body)
    old_messages = _parse_chat_body(content)
    stat = md_path.stat()
    new_messages = [
        SessionMessage(
            role=m.role,
            content=RichContent(format=ContentFormat.markdown, value=m.content),
            timestamp=m.timestamp,
            footnotes=m.footnotes,
            tool_calls=m.tool_calls,
            model=m.model,
        )
        for m in old_messages
    ]
    slug = _file_slug(md_path.stem)
    return ChatSession(
        slug=slug,
        title=fm.get("title") or md_path.stem,
        tags=list(fm.get("tags") or []),
        messages=new_messages,
        model=fm.get("model", "llama3"),
        pinned_turns=list(fm.get("pinned_turns") or []),
        excerpt_slug=fm.get("excerpt_slug"),
        path=md_path.with_suffix(".sess"),
        created_at=datetime.fromtimestamp(stat.st_mtime),
        modified_at=datetime.fromtimestamp(stat.st_mtime),
    )


def migrate_chats_to_sess(
    vault: VaultService, *, dry_run: bool = True, remove_md: bool = False,
) -> list[ChatMigrationResult]:
    """Converts every vault/chats/*.md file to a sibling .sess file.
    dry_run=True (the default) reports what would happen without writing
    anything. remove_md only takes effect when dry_run=False -- deletes the
    source .md once its .sess has been written successfully, never on a
    conversion that errored."""
    chats_dir = vault.default_dirs[NodeType.chat]
    results: list[ChatMigrationResult] = []
    for md_path in sorted(chats_dir.glob("*.md")):
        sess_path = md_path.with_suffix(".sess")
        try:
            session = _convert_one(md_path)
        except Exception as exc:
            results.append(ChatMigrationResult(
                slug=md_path.stem, md_path=md_path, sess_path=sess_path, message_count=0, error=str(exc),
            ))
            continue
        if not dry_run:
            save_chat_session(session, sess_path)
            if remove_md:
                md_path.unlink()
        results.append(ChatMigrationResult(
            slug=session.slug, md_path=md_path, sess_path=sess_path, message_count=len(session.messages),
        ))
    return results
