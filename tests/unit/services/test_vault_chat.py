"""Unit tests for chat persistence in VaultService (ADR-019) -- pure-JSON
`.sess` storage for the live path, plus the legacy `.md` read-only parser
kept solely for chat_migration.migrate_chats_to_sess."""
import json

import pytest

from prisma.schema_gov import ContentFormat, RichContent
from prisma.services.vault import CHAT_META_SCHEMA_VERSION, VaultService, _migrate_chat_meta, _parse_chat_body
from prisma.storage.models.vault_models import ChatMessage, ChatRole, Footnote, FootnoteRelation, ToolCallRecord


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


# ── Legacy .md read path (chat_migration's only remaining consumer) ──────────

def test_parse_chat_body_message_with_no_tool_calls():
    body = "### You\n\njust chatting\n\n### Prisma\n\nsure, how can I help?\n\n"
    parsed = _parse_chat_body(body)
    assert parsed[0].tool_calls == []
    assert parsed[1].tool_calls == []


def test_parse_chat_body_returns_rich_content_markdown_messages():
    body = "### You\n\nWhat have I written about attention?\n\n"
    parsed = _parse_chat_body(body)
    assert parsed[0].content.format == ContentFormat.markdown
    assert parsed[0].content.value == "What have I written about attention?"


def test_parse_chat_body_extracts_tool_call_line():
    body = (
        "### Prisma\n\n"
        "> used `search_vault`: attention\n\n"
        "Based on your notes...\n\n"
    )
    parsed = _parse_chat_body(body)
    assert parsed[0].tool_calls == [ToolCallRecord(tool="search_vault", args={"query": "attention"})]
    assert "Based on your notes..." in parsed[0].content.value
    assert "used `search_vault`" not in parsed[0].content.value


def test_parse_chat_body_extracts_model_and_footnotes_from_meta_comment():
    footnote = {
        "index": 1, "relation": "citation", "sources": ["attention-is-all-you-need"],
        "claim_text": "The Transformer achieves 28.4 BLEU.", "faithfulness_checked": False,
    }
    meta = json.dumps({"schema_version": CHAT_META_SCHEMA_VERSION, "model": "qwen2.5-3b", "footnotes": [footnote]})
    body = f"### Prisma\n\n<!-- prisma:meta {meta} -->\nIt achieves 28.4 BLEU.[^1]\n\n"
    parsed = _parse_chat_body(body)
    assert parsed[0].model == "qwen2.5-3b"
    assert parsed[0].footnotes == [Footnote.model_validate(footnote)]
    assert "It achieves 28.4 BLEU.[^1]" in parsed[0].content.value
    assert "prisma:meta" not in parsed[0].content.value


def test_parse_chat_body_ignores_malformed_meta_comment():
    body = "### Prisma\n\n<!-- prisma:meta {not valid json} -->\nstill here\n\n"
    parsed = _parse_chat_body(body)
    assert parsed[0].model is None
    assert parsed[0].footnotes == []
    assert "still here" in parsed[0].content.value


def test_migrate_chat_meta_treats_absent_schema_version_as_v1():
    # Pre-governance meta blobs (written the same day this field was added,
    # before it existed) already match v1's shape -- must still load, not
    # be rejected as "no version, therefore invalid."
    migrated = _migrate_chat_meta({"model": "test-model"})
    assert migrated == {"model": "test-model"}


def test_migrate_chat_meta_passes_through_current_version_unchanged():
    raw = {"schema_version": CHAT_META_SCHEMA_VERSION, "model": "test-model"}
    assert _migrate_chat_meta(raw) == raw


def test_migrate_chat_meta_raises_for_a_version_newer_than_this_build_supports():
    with pytest.raises(ValueError, match="newer than this build supports"):
        _migrate_chat_meta({"schema_version": CHAT_META_SCHEMA_VERSION + 1})


def test_parse_chat_body_degrades_gracefully_for_a_too_new_schema_version():
    # _migrate_chat_meta's ValueError falls into the same try/except that
    # already handles a malformed/hand-edited meta comment (composes for
    # free, no new handling needed) -- an older binary reading a file a
    # newer one wrote loses that turn's metadata, not the whole chat.
    too_new = CHAT_META_SCHEMA_VERSION + 1
    body = f'### Prisma\n\n<!-- prisma:meta {{"schema_version": {too_new}}} -->\nstill here\n\n'
    parsed = _parse_chat_body(body)
    assert parsed[0].model is None
    assert parsed[0].footnotes == []
    assert "still here" in parsed[0].content.value


# ── Live .sess path ────────────────────────────────────────────────────────

def _msg(role: ChatRole, text: str, **overrides) -> ChatMessage:
    return ChatMessage(role=role, content=RichContent(format=ContentFormat.markdown, value=text), **overrides)


def test_create_chat_writes_a_sess_file(vault):
    chat = vault.create_chat("Test Session", model="qwen2.5:7b")
    raw = json.loads((vault.root / "chats" / f"{chat.slug}.sess").read_text(encoding="utf-8"))
    assert raw["node_type"] == "chat"
    assert chat.model == "qwen2.5:7b"
    assert chat.messages == []


def test_save_chat_then_get_chat_roundtrip(vault):
    chat = vault.create_chat("Test Session")
    messages = [
        _msg(ChatRole.user, "hello"),
        _msg(ChatRole.assistant, "hi! I searched your vault.",
             tool_calls=[ToolCallRecord(tool="search_vault", args={"query": "hello"})]),
    ]
    vault.save_chat(chat.slug, messages)

    reloaded = vault.get_chat(chat.slug)
    assert len(reloaded.messages) == 2
    assert reloaded.messages[1].tool_calls[0].tool == "search_vault"
    assert reloaded.model == chat.model  # unchanged across save


def test_append_messages_appends_to_current_disk_state_not_a_stale_snapshot(vault):
    # Regression: /chat used to write `history + [new turns]` from a
    # `history` snapshot taken *before* a possibly-slow LLM call — if
    # something else (e.g. a delete) changed the chat's messages while that
    # call was running, the eventual write would silently revert it.
    # append_messages must always append onto whatever's on disk *right
    # now*, not a caller-held snapshot.
    chat = vault.create_chat("Test Session")
    vault.save_chat(chat.slug, [_msg(ChatRole.user, "original")])

    # Simulate something else changing the chat on disk after a caller
    # would have taken its own snapshot.
    vault.save_chat(chat.slug, [
        _msg(ChatRole.user, "original"),
        _msg(ChatRole.assistant, "inserted by someone else"),
    ])

    updated = vault.append_messages(chat.slug, [_msg(ChatRole.user, "new turn")])

    contents = [m.content.value for m in updated.messages]
    assert contents == ["original", "inserted by someone else", "new turn"]


def test_append_messages_updates_model_like_save_chat(vault):
    chat = vault.create_chat("Test Session", model="old-model")

    updated = vault.append_messages(chat.slug, [_msg(ChatRole.user, "hi")], model="new-model")

    assert updated.model == "new-model"


def test_append_messages_raises_for_missing_chat(vault):
    with pytest.raises(FileNotFoundError):
        vault.append_messages("does-not-exist", [_msg(ChatRole.user, "x")])


def test_get_any_dispatches_chat_type_to_get_chat(vault):
    chat = vault.create_chat("Test Session")
    result = vault.get_any(chat.slug)
    assert result.node_type.value == "chat"
    assert result.slug == chat.slug


def test_slug_exists_finds_a_chat(vault):
    chat = vault.create_chat("Test Session")
    assert vault.slug_exists(chat.slug)


def test_unique_slug_disambiguates_against_an_existing_chat(vault):
    vault.create_chat("Duplicate Title")
    second = vault.create_chat("Duplicate Title")
    assert second.slug != "duplicate-title"


def test_delete_node_removes_a_chat(vault):
    chat = vault.create_chat("Test Session")
    vault.delete_node(chat.slug)
    assert not vault.slug_exists(chat.slug)


def test_rename_node_renames_a_chat_file_and_title(vault):
    chat = vault.create_chat("Original Title")
    new_slug = vault.rename_node(chat.slug, "New Title")

    assert not (vault.root / "chats" / f"{chat.slug}.sess").exists()
    reloaded = vault.get_chat(new_slug)
    assert reloaded.title == "New Title"
    assert reloaded.slug == new_slug


# ── Excerpt: one Excerpt note per chat, Summary + pinned turns (ADR-015) ──────

def test_save_excerpt_creates_note_with_excerpt_of_chat(vault):
    chat = vault.create_chat("Research Session")
    turns = [_msg(ChatRole.user, "We agreed to use Kùzu, not Neo4j.")]

    note = vault.save_excerpt(chat.slug, "We chose Kùzu over Neo4j.", turns)

    assert note.excerpt_of_chat == chat.slug
    raw = (vault.root / "notes" / f"{note.slug}.md").read_text(encoding="utf-8")
    assert f"excerpt_of_chat: {chat.slug}" in raw
    assert "We chose Kùzu over Neo4j." in raw


def test_save_excerpt_records_slug_on_chat(vault):
    chat = vault.create_chat("Research Session")

    note = vault.save_excerpt(chat.slug, "Settled.", [])

    reloaded = vault.get_chat(chat.slug)
    assert reloaded.excerpt_slug == note.slug


def test_save_excerpt_reuses_existing_note_instead_of_creating_another(vault):
    chat = vault.create_chat("Research Session")
    first = vault.save_excerpt(chat.slug, "First summary.", [])

    second = vault.save_excerpt(chat.slug, "Second summary.", [])

    assert second.slug == first.slug
    reloaded_note = vault.get_note(first.slug)
    assert "Second summary." in reloaded_note.body
    assert len(list((vault.root / "notes").glob("*.md"))) == 1


def test_save_excerpt_raises_for_missing_chat(vault):
    with pytest.raises(FileNotFoundError):
        vault.save_excerpt("does-not-exist", "X", [])


def test_save_excerpt_recreates_note_if_excerpt_slug_points_to_a_deleted_note(vault):
    # Real bug found in self-audit: the generic delete-node endpoint has no
    # special case for clearing Chat.excerpt_slug, so deleting the Excerpt
    # note directly used to permanently break every future pin/unpin for
    # that chat (save_note raised FileNotFoundError, silently swallowed by
    # the caller). Must fall back to creating a fresh note instead.
    chat = vault.create_chat("Research Session")
    first = vault.save_excerpt(chat.slug, "First summary.", [])
    (vault.root / "notes" / f"{first.slug}.md").unlink()  # simulate deletion out from under excerpt_slug

    second = vault.save_excerpt(chat.slug, "Second summary.", [])

    assert (vault.root / "notes" / f"{second.slug}.md").exists()
    reloaded = vault.get_chat(chat.slug)
    assert reloaded.excerpt_slug == second.slug
    assert "Second summary." in vault.get_note(second.slug).body


def test_save_excerpt_verbatim_mode_omits_summary_section(vault):
    # summary=None is ADR-015's verbatim mode — no LLM call happened, so
    # there's nothing to show under a "Summary" heading at all.
    chat = vault.create_chat("Research Session")
    turns = [_msg(ChatRole.user, "Kept exactly as written.")]

    note = vault.save_excerpt(chat.slug, None, turns)

    assert "## Summary" not in note.body
    assert "## Pinned turns" in note.body
    assert "Kept exactly as written." in note.body


def test_save_excerpt_renders_each_pinned_turn_as_its_own_block(vault):
    chat = vault.create_chat("Research Session")
    turns = [
        _msg(ChatRole.user, "First pinned turn."),
        _msg(ChatRole.assistant, "Second pinned turn."),
    ]

    note = vault.save_excerpt(chat.slug, "A summary.", turns)

    assert "### You\n\nFirst pinned turn." in note.body
    assert "### Prisma\n\nSecond pinned turn." in note.body
    assert "---" in note.body  # separates the two turn blocks


def test_set_pinned_turns_records_indices_on_chat(vault):
    chat = vault.create_chat("Research Session")
    vault.save_chat(chat.slug, [_msg(ChatRole.user, "a"), _msg(ChatRole.assistant, "b")])

    vault.set_pinned_turns(chat.slug, [0])

    reloaded = vault.get_chat(chat.slug)
    assert reloaded.pinned_turns == [0]


def test_set_pinned_turns_raises_for_missing_chat(vault):
    with pytest.raises(FileNotFoundError):
        vault.set_pinned_turns("does-not-exist", [0])


# ── Tree: chats and Excerpts already shown in dedicated sidebar sections ──────

def test_get_tree_excludes_chats_dir(vault):
    vault.create_chat("Research Session")

    names = [n.name for n in vault.get_tree()]

    assert "chats" not in names


def test_get_tree_excludes_excerpt_notes(vault):
    chat = vault.create_chat("Research Session")
    vault.save_excerpt(chat.slug, "Settled.", [])
    vault.create_note("A Real Note", body="Some content.")

    notes_dir = next(n for n in vault.get_tree() if n.name == "notes")
    file_names = [c.name for c in notes_dir.children]

    assert not any(name.startswith("excerpt-") for name in file_names)
    assert any("a-real-note" in name for name in file_names)


# ── Listing ────────────────────────────────────────────────────────────────

def test_list_nodes_includes_chats(vault):
    chat = vault.create_chat("Research Session")

    listing = vault.list_nodes()

    assert [c.slug for c in listing.chats] == [chat.slug]


def test_list_nodes_populates_both_chats_and_notes_buckets(vault):
    vault.create_chat("Research Session")
    vault.create_note("A Note", body="content")

    listing = vault.list_nodes()

    assert len(listing.chats) == 1
    assert len(listing.notes) == 1
