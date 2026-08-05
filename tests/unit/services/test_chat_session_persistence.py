"""Unit tests for Chat .sess file persistence (ADR-019) -- pure JSON,
low-level load_chat_session/save_chat_session round-trip. Higher-level
VaultService chat CRUD is covered in test_vault_chat.py."""
import json
from pathlib import Path

import pytest

from prisma.schema_gov import RichContent
from prisma.services.vault import load_chat_session, save_chat_session
from prisma.storage.models.vault_models import Chat, ChatMessage, ChatRole


@pytest.fixture
def sess_path(tmp_path) -> Path:
    return tmp_path / "test-chat.sess"


def _chat(**overrides) -> Chat:
    defaults = dict(slug="test-chat", title="Test Chat", path=Path("/unused"))
    defaults.update(overrides)
    return Chat(**defaults)


def test_save_writes_valid_json(sess_path):
    save_chat_session(_chat(), sess_path)
    raw = json.loads(sess_path.read_text(encoding="utf-8"))
    assert raw["slug"] == "test-chat"
    assert raw["schema_version"] == 1


def test_save_excludes_path_from_file_content(sess_path):
    save_chat_session(_chat(), sess_path)
    raw = json.loads(sess_path.read_text(encoding="utf-8"))
    assert "path" not in raw


def test_save_excludes_response_only_fields_from_file_content(sess_path):
    chat = _chat(context_tokens_used=123, context_tokens_max=456, excerpt_regenerating=True)
    save_chat_session(chat, sess_path)
    raw = json.loads(sess_path.read_text(encoding="utf-8"))
    assert "context_tokens_used" not in raw
    assert "context_tokens_max" not in raw
    assert "excerpt_regenerating" not in raw
    assert "excerpt_summary_html" not in raw


def test_load_reinjects_the_actual_file_path(sess_path):
    save_chat_session(_chat(), sess_path)
    loaded = load_chat_session(sess_path)
    assert loaded.path == sess_path


def test_round_trip_preserves_messages(sess_path):
    chat = _chat(
        messages=[
            ChatMessage(role=ChatRole.user, content=RichContent(value="hi")),
            ChatMessage(role=ChatRole.assistant, content=RichContent(value="hello[^1]"), model="qwen2.5-3b"),
        ],
    )
    save_chat_session(chat, sess_path)
    loaded = load_chat_session(sess_path)
    assert len(loaded.messages) == 2
    assert loaded.messages[1].content.value == "hello[^1]"
    assert loaded.messages[1].model == "qwen2.5-3b"
