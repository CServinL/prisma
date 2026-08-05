"""Unit tests for ChatSession .sess file persistence (ADR-019) -- pure
JSON, additive alongside the existing markdown Chat/_parse_chat_body path."""
import json
from pathlib import Path

import pytest

from prisma.schema_gov import RichContent
from prisma.services.vault import load_chat_session, save_chat_session
from prisma.storage.models.vault_models import ChatRole, ChatSession, SessionMessage


@pytest.fixture
def sess_path(tmp_path) -> Path:
    return tmp_path / "test-chat.sess"


def _session(**overrides) -> ChatSession:
    defaults = dict(slug="test-chat", title="Test Chat", path=Path("/unused"))
    defaults.update(overrides)
    return ChatSession(**defaults)


def test_save_writes_valid_json(sess_path):
    save_chat_session(_session(), sess_path)
    raw = json.loads(sess_path.read_text(encoding="utf-8"))
    assert raw["slug"] == "test-chat"
    assert raw["schema_version"] == 1


def test_save_excludes_path_from_file_content(sess_path):
    save_chat_session(_session(), sess_path)
    raw = json.loads(sess_path.read_text(encoding="utf-8"))
    assert "path" not in raw


def test_load_reinjects_the_actual_file_path(sess_path):
    save_chat_session(_session(), sess_path)
    loaded = load_chat_session(sess_path)
    assert loaded.path == sess_path


def test_round_trip_preserves_messages(sess_path):
    session = _session(
        messages=[
            SessionMessage(role=ChatRole.user, content=RichContent(value="hi")),
            SessionMessage(role=ChatRole.assistant, content=RichContent(value="hello[^1]"), model="qwen2.5-3b"),
        ],
    )
    save_chat_session(session, sess_path)
    loaded = load_chat_session(sess_path)
    assert len(loaded.messages) == 2
    assert loaded.messages[1].content.value == "hello[^1]"
    assert loaded.messages[1].model == "qwen2.5-3b"
