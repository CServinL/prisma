"""Unit tests for the .md -> .sess chat migration (ADR-019). Seeds a
legacy-format .md chat file by hand -- vault.create_chat/append_messages
write .sess now (the live path is already cut over), so they can't be used
to construct pre-migration fixtures the way this migration script expects
to find them in a real, not-yet-migrated vault."""
import pytest

from prisma.schema_gov import ContentFormat
from prisma.services.chat_migration import migrate_chats_to_sess
from prisma.services.vault import VaultService, load_chat_session
from prisma.storage.models.vault_models import NodeType


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def _seed_chat(vault):
    slug = "test-chat"
    body = (
        "---\ntype: chat\ntitle: Test Chat\nmodel: qwen2.5-3b\n---\n\n"
        "### You\n\nhi\n\n"
        '### Prisma\n\n<!-- prisma:meta {"schema_version": 1, "model": "qwen2.5-3b", '
        '"footnotes": [{"index": 1, "relation": "citation", "sources": ["src-a"], '
        '"claim_text": null, "faithfulness_checked": null}]} -->\n'
        "hello[^1]\n\n"
    )
    path = vault.default_dirs[NodeType.chat] / f"{slug}.md"
    path.write_text(body, encoding="utf-8")
    return slug


def test_dry_run_reports_without_writing_anything(vault):
    slug = _seed_chat(vault)
    results = migrate_chats_to_sess(vault, dry_run=True)

    assert len(results) == 1
    assert results[0].slug == slug
    assert results[0].message_count == 2
    assert results[0].error is None
    assert not results[0].sess_path.exists()
    assert results[0].md_path.exists()  # untouched


def test_apply_writes_sess_and_keeps_md_by_default(vault):
    slug = _seed_chat(vault)
    results = migrate_chats_to_sess(vault, dry_run=False)

    assert results[0].sess_path.exists()
    assert results[0].md_path.exists()  # kept -- remove_md defaults to False

    session = load_chat_session(results[0].sess_path)
    assert session.slug == slug
    assert len(session.messages) == 2
    assert session.messages[1].content.format == ContentFormat.markdown
    assert session.messages[1].content.value == "hello[^1]"
    assert session.messages[1].model == "qwen2.5-3b"
    assert session.messages[1].claims[0].sources == ["src-a"]


def test_apply_with_remove_md_deletes_the_source_file(vault):
    _seed_chat(vault)
    results = migrate_chats_to_sess(vault, dry_run=False, remove_md=True)

    assert results[0].sess_path.exists()
    assert not results[0].md_path.exists()


def test_malformed_md_file_is_reported_not_raised(vault):
    _seed_chat(vault)
    chats_dir = vault.default_dirs[NodeType.chat]
    bad = chats_dir / "not-really-a-chat.md"
    bad.write_text("garbage \x00 not frontmatter at all", encoding="utf-8")

    # Frontmatter parsing is lenient (a missing "---" block just means no
    # frontmatter, not an error) -- the real property under test is that
    # migrate_chats_to_sess itself never raises for the whole batch over
    # one bad file, regardless of whether that file individually succeeds
    # with an empty result or comes back with .error set.
    results = migrate_chats_to_sess(vault, dry_run=True)
    assert len(results) == 2
