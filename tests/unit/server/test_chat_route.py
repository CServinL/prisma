"""Unit tests for app.py's POST /chat route -- in particular that footnotes
(ADR-017) flow all the way from ChatAgent.respond() through to the API
response, since this route has no isolated-router test file yet (unlike
notes_routes.py etc.) -- it still lives directly in app.py.
"""
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from prisma.schema_gov import RichContent
from prisma.server.app import app
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import Chat, ChatMessage, ChatRole, Footnote, NodeType

client = TestClient(app, client=("127.0.0.1", 12345))


def _chat(slug: str = "test-chat") -> Chat:
    return Chat(slug=slug, title="Test Chat", node_type=NodeType.chat, path=Path(f"/tmp/{slug}.sess"), messages=[])


def _msg(role: ChatRole, text: str, **overrides) -> ChatMessage:
    return ChatMessage(role=role, content=RichContent(value=text), **overrides)


def test_chat_route_returns_footnotes_from_assistant_message(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    assistant_msg = _msg(
        ChatRole.assistant, "Kùzu was chosen for its embedded mode[^1].",
        footnotes=[Footnote(index=1, relation="attribution", sources=["kg-decision"])],
    )
    chat_agent = MagicMock()
    chat_agent.respond.return_value = assistant_msg
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "why Kùzu?", "chat_slug": "test-chat"})

    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "Kùzu was chosen for its embedded mode[^1]."
    assert data["footnotes"] == [
        {"index": 1, "relation": "attribution", "sources": ["kg-decision"],
         "claim_text": None, "faithfulness_checked": None},
    ]
    vault.append_messages.assert_called_once()


def test_chat_route_footnotes_default_to_empty_list(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    chat_agent = MagicMock()
    chat_agent.respond.return_value = _msg(ChatRole.assistant, "A plain answer.")
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "hello", "chat_slug": "test-chat"})

    assert r.status_code == 200
    assert r.json()["footnotes"] == []


def test_chat_route_returns_sanitized_html_with_footnote_marker_span(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    # A real VaultService, not a MagicMock -- _render_chat_html actually
    # renders through docu_craft (citekey indexing, etc.), which a mock
    # vault can't support. get_chat/append_messages work fine against it
    # directly since it's a real chat created via create_chat below.
    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)

    assistant_msg = _msg(
        ChatRole.assistant, "Some reply with a claim.[^1]\n\n<script>alert(1)</script>",
        footnotes=[Footnote(index=1, relation="ai-inference", sources=[])],
    )
    chat_agent = MagicMock()
    chat_agent.respond.return_value = assistant_msg
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "hello", "chat_slug": chat_slug})

    assert r.status_code == 200
    html = r.json()["html"]
    assert '<span class="footnote-marker" data-footnote-index="1">1</span>' in html
    assert "<script" not in html
    assert "alert(1)" not in html


def test_get_chat_route_populates_html_on_historical_assistant_messages(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat = real_vault.create_chat(title="Test Chat")
    real_vault.append_messages(chat.slug, [
        _msg(ChatRole.user, "hi"),
        _msg(ChatRole.assistant, "A reply.[^1]", model="test-model",
             footnotes=[Footnote(index=1, relation="ai-inference", sources=[])]),
    ])
    monkeypatch.setattr(app_module, "_vault", real_vault)
    chat_agent = MagicMock()
    chat_agent.context_usage.return_value = (10, 16000)
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.get(f"/chats/{chat.slug}")

    assert r.status_code == 200
    messages = r.json()["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"]["rendered_html"] is None
    assert messages[1]["role"] == "assistant"
    assert '<span class="footnote-marker" data-footnote-index="1">1</span>' in messages[1]["content"]["rendered_html"]


def test_chat_route_404_when_chat_not_found(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.side_effect = FileNotFoundError()
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post("/chat", json={"message": "hello", "chat_slug": "missing-chat"})

    assert r.status_code == 404


# ── POST /chats/{slug}/turns/{index}/regenerate (ADR-019 §6a) ────────────────

def _seeded_regen_vault(tmp_path):
    vault = VaultService(vault_root=tmp_path / "vault")
    vault.ensure_dirs()
    chat = vault.create_chat(title="Test Chat", model="qwen2.5-3b")
    vault.append_messages(chat.slug, [
        _msg(ChatRole.user, "why Kùzu?"),
        _msg(ChatRole.assistant, "v1 answer", model="qwen2.5-3b"),
    ], model="qwen2.5-3b")
    return vault, chat.slug


def test_regenerate_turn_replaces_content_and_preserves_alternate(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    vault, slug = _seeded_regen_vault(tmp_path)
    monkeypatch.setattr(app_module, "_vault", vault)
    chat_agent = MagicMock()
    chat_agent.respond.return_value = _msg(ChatRole.assistant, "v2 answer", model="qwen2.5-3b")
    chat_agent.model = "qwen2.5-3b"
    chat_agent.context_usage.return_value = (10, 16000)
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post(f"/chats/{slug}/turns/1/regenerate", json={})

    assert r.status_code == 200
    messages = r.json()["messages"]
    assert messages[1]["content"]["value"] == "v2 answer"
    assert len(messages[1]["alternates"]) == 1
    assert messages[1]["alternates"][0]["content"]["value"] == "v1 answer"
    chat_agent.respond.assert_called_once()
    history_arg = chat_agent.respond.call_args[0][0]
    assert history_arg == []  # nothing before the user turn at index 0


def test_regenerate_turn_with_model_override_does_not_change_chat_model(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    vault, slug = _seeded_regen_vault(tmp_path)
    monkeypatch.setattr(app_module, "_vault", vault)
    override_agent = MagicMock()
    override_agent.respond.return_value = _msg(ChatRole.assistant, "v2 from bigger model", model="qwen2.5-7b")
    override_agent.model = "qwen2.5-7b"
    monkeypatch.setattr(app_module, "_build_chat_agent_for_model", lambda model: override_agent)

    r = client.post(f"/chats/{slug}/turns/1/regenerate", json={"model": "qwen2.5-7b"})

    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "qwen2.5-3b"  # chat's own configured model is untouched
    assert data["messages"][1]["content"]["value"] == "v2 from bigger model"
    assert data["messages"][1]["model"] == "qwen2.5-7b"


def test_regenerate_turn_404_when_chat_not_found(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.side_effect = FileNotFoundError()
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post("/chats/missing-chat/turns/0/regenerate", json={})

    assert r.status_code == 404


def test_regenerate_turn_400_for_a_user_turn(tmp_path, monkeypatch):
    from prisma.server import app as app_module

    vault, slug = _seeded_regen_vault(tmp_path)
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post(f"/chats/{slug}/turns/0/regenerate", json={})

    assert r.status_code == 400


def test_regenerate_turn_400_for_an_out_of_range_index(tmp_path, monkeypatch):
    from prisma.server import app as app_module

    vault, slug = _seeded_regen_vault(tmp_path)
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post(f"/chats/{slug}/turns/5/regenerate", json={})

    assert r.status_code == 400
