"""Unit tests for chat transcript persistence in VaultService — plain
markdown storage, role-heading convention, tool-call lines."""
import pytest

from prisma.services.vault import VaultService, _parse_chat_body, _render_chat_body
from prisma.storage.models.vault_models import ChatMessage, ChatRole, ToolCallRecord


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_render_chat_body_uses_role_headings():
    messages = [
        ChatMessage(role=ChatRole.user, content="hi there"),
        ChatMessage(role=ChatRole.assistant, content="hello!"),
    ]
    body = _render_chat_body(messages)
    assert "### You" in body
    assert "hi there" in body
    assert "### Prisma" in body
    assert "hello!" in body
    assert body.index("### You") < body.index("### Prisma")


def test_render_chat_body_includes_tool_call_line():
    messages = [
        ChatMessage(
            role=ChatRole.assistant,
            content="Based on your notes...",
            tool_calls=[ToolCallRecord(tool="search_vault", args={"query": "attention"})],
        ),
    ]
    body = _render_chat_body(messages)
    assert "> used `search_vault`: attention" in body
    assert "Based on your notes..." in body


def test_render_parse_roundtrip_preserves_role_content_and_tool_calls():
    messages = [
        ChatMessage(role=ChatRole.user, content="What have I written about attention?"),
        ChatMessage(
            role=ChatRole.assistant,
            content="You've written about attention mechanisms in transformers.",
            tool_calls=[ToolCallRecord(tool="search_vault", args={"query": "attention"})],
        ),
    ]
    body = _render_chat_body(messages)
    parsed = _parse_chat_body(body)

    assert len(parsed) == 2
    assert parsed[0].role == ChatRole.user
    assert parsed[0].content == "What have I written about attention?"
    assert parsed[1].role == ChatRole.assistant
    assert parsed[1].tool_calls == [ToolCallRecord(tool="search_vault", args={"query": "attention"})]
    assert "attention mechanisms in transformers" in parsed[1].content


def test_parse_chat_body_message_with_no_tool_calls():
    body = "### You\n\njust chatting\n\n### Prisma\n\nsure, how can I help?\n\n"
    parsed = _parse_chat_body(body)
    assert parsed[0].tool_calls == []
    assert parsed[1].tool_calls == []


def test_create_chat_writes_type_chat_frontmatter(vault):
    chat = vault.create_chat("Test Session", model="qwen2.5:7b")
    raw = (vault.root / "chats" / f"{chat.slug}.md").read_text(encoding="utf-8")
    assert "type: chat" in raw
    assert chat.model == "qwen2.5:7b"
    assert chat.messages == []


def test_save_chat_then_get_chat_roundtrip(vault):
    chat = vault.create_chat("Test Session")
    messages = [
        ChatMessage(role=ChatRole.user, content="hello"),
        ChatMessage(
            role=ChatRole.assistant,
            content="hi! I searched your vault.",
            tool_calls=[ToolCallRecord(tool="search_vault", args={"query": "hello"})],
        ),
    ]
    vault.save_chat(chat.slug, messages)

    reloaded = vault.get_chat(chat.slug)
    assert len(reloaded.messages) == 2
    assert reloaded.messages[1].tool_calls[0].tool == "search_vault"
    assert reloaded.model == chat.model  # frontmatter preserved across save


def test_append_messages_appends_to_current_disk_state_not_a_stale_snapshot(vault):
    # Regression: /chat used to write `history + [new turns]` from a
    # `history` snapshot taken *before* a possibly-slow LLM call — if
    # something else (e.g. a delete) changed the chat's messages while that
    # call was running, the eventual write would silently revert it.
    # append_messages must always append onto whatever's on disk *right
    # now*, not a caller-held snapshot.
    chat = vault.create_chat("Test Session")
    vault.save_chat(chat.slug, [ChatMessage(role=ChatRole.user, content="original")])

    # Simulate something else changing the chat on disk after a caller
    # would have taken its own snapshot.
    vault.save_chat(chat.slug, [
        ChatMessage(role=ChatRole.user, content="original"),
        ChatMessage(role=ChatRole.assistant, content="inserted by someone else"),
    ])

    updated = vault.append_messages(chat.slug, [ChatMessage(role=ChatRole.user, content="new turn")])

    contents = [m.content for m in updated.messages]
    assert contents == ["original", "inserted by someone else", "new turn"]


def test_append_messages_updates_model_like_save_chat(vault):
    chat = vault.create_chat("Test Session", model="old-model")

    updated = vault.append_messages(chat.slug, [ChatMessage(role=ChatRole.user, content="hi")], model="new-model")

    assert updated.model == "new-model"


def test_append_messages_raises_for_missing_chat(vault):
    with pytest.raises(FileNotFoundError):
        vault.append_messages("does-not-exist", [ChatMessage(role=ChatRole.user, content="x")])


def test_get_any_dispatches_chat_type_to_get_chat(vault):
    chat = vault.create_chat("Test Session")
    result = vault.get_any(chat.slug)
    assert result.node_type.value == "chat"
    assert result.slug == chat.slug


# ── Excerpt: one Excerpt note per chat, Summary + pinned turns (ADR-015) ──────

def test_save_excerpt_creates_note_with_promoted_from_chat(vault):
    chat = vault.create_chat("Research Session")
    turns = [ChatMessage(role=ChatRole.user, content="We agreed to use Kùzu, not Neo4j.")]

    note = vault.save_excerpt(chat.slug, "We chose Kùzu over Neo4j.", turns)

    assert note.promoted_from_chat == chat.slug
    raw = (vault.root / "notes" / f"{note.slug}.md").read_text(encoding="utf-8")
    assert f"promoted_from_chat: {chat.slug}" in raw
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
    turns = [ChatMessage(role=ChatRole.user, content="Kept exactly as written.")]

    note = vault.save_excerpt(chat.slug, None, turns)

    assert "## Summary" not in note.body
    assert "## Pinned turns" in note.body
    assert "Kept exactly as written." in note.body


def test_save_excerpt_renders_each_pinned_turn_as_its_own_block(vault):
    chat = vault.create_chat("Research Session")
    turns = [
        ChatMessage(role=ChatRole.user, content="First pinned turn."),
        ChatMessage(role=ChatRole.assistant, content="Second pinned turn."),
    ]

    note = vault.save_excerpt(chat.slug, "A summary.", turns)

    assert "### You\n\nFirst pinned turn." in note.body
    assert "### Prisma\n\nSecond pinned turn." in note.body
    assert "---" in note.body  # separates the two turn blocks


def test_set_pinned_turns_records_indices_on_chat(vault):
    chat = vault.create_chat("Research Session")
    vault.save_chat(chat.slug, [
        ChatMessage(role=ChatRole.user, content="a"),
        ChatMessage(role=ChatRole.assistant, content="b"),
    ])

    vault.set_pinned_turns(chat.slug, [0])

    reloaded = vault.get_chat(chat.slug)
    assert reloaded.pinned_turns == [0]


def test_set_pinned_turns_raises_for_missing_chat(vault):
    with pytest.raises(FileNotFoundError):
        vault.set_pinned_turns("does-not-exist", [0])
