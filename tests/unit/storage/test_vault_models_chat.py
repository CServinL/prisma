"""Unit tests for ChatSession/SessionMessage (ADR-019) -- the pure-JSON
.sess replacement for the Chat/ChatMessage markdown-with-embedded-comment
shape. Round-trip, versioning (via schema_gov.VersionedModel), and the
2026-08-04 alternates decision."""
from pathlib import Path

from prisma.schema_gov import ContentFormat, RichContent
from prisma.storage.models.vault_models import (
    CHAT_SESSION_SCHEMA_VERSION, ChatRole, ChatSession, Footnote, FootnoteRelation,
    NodeType, SessionMessage, ToolCallRecord,
)


def _session(**overrides) -> ChatSession:
    defaults = dict(slug="test-chat", title="Test Chat", path=Path("/tmp/test-chat.sess"))
    defaults.update(overrides)
    return ChatSession(**defaults)


def test_new_chat_session_gets_current_schema_version():
    s = _session()
    assert s.schema_version == CHAT_SESSION_SCHEMA_VERSION


def test_node_type_defaults_to_chat():
    assert _session().node_type == NodeType.chat


def test_session_message_content_is_rich_content():
    msg = SessionMessage(role=ChatRole.assistant, content=RichContent(value="hello"))
    assert msg.content.format == ContentFormat.markdown
    assert msg.content.value == "hello"


def test_round_trip_through_json_preserves_messages_footnotes_and_model():
    s = _session(
        messages=[
            SessionMessage(role=ChatRole.user, content=RichContent(value="hi")),
            SessionMessage(
                role=ChatRole.assistant,
                content=RichContent(value="answer[^1]"),
                model="qwen2.5-3b",
                footnotes=[Footnote(index=1, relation=FootnoteRelation.citation, sources=["src-a"])],
                tool_calls=[ToolCallRecord(tool="search_vault", args={"query": "x"})],
            ),
        ],
    )
    restored = ChatSession.model_validate_json(s.model_dump_json())
    assert len(restored.messages) == 2
    assert restored.messages[1].model == "qwen2.5-3b"
    assert restored.messages[1].content.value == "answer[^1]"
    assert restored.messages[1].footnotes[0].sources == ["src-a"]
    assert restored.messages[1].tool_calls[0].tool == "search_vault"


def test_alternates_preserve_prior_regeneration_attempts():
    old_attempt = SessionMessage(role=ChatRole.assistant, content=RichContent(value="v1 answer"), model="qwen2.5-3b")
    live = SessionMessage(
        role=ChatRole.assistant, content=RichContent(value="v2 answer"), model="qwen2.5-7b",
        alternates=[old_attempt],
    )
    restored = SessionMessage.model_validate_json(live.model_dump_json())
    assert restored.content.value == "v2 answer"
    assert restored.model == "qwen2.5-7b"
    assert len(restored.alternates) == 1
    assert restored.alternates[0].content.value == "v1 answer"
    assert restored.alternates[0].model == "qwen2.5-3b"


def test_absent_schema_version_in_raw_json_is_treated_as_v1():
    # A hand-constructed or otherwise pre-versioning raw dict must still load.
    raw = {"slug": "x", "title": "X", "path": "/tmp/x.sess"}
    s = ChatSession.model_validate(raw)
    assert s.schema_version == CHAT_SESSION_SCHEMA_VERSION
