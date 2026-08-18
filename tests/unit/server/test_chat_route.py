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
from prisma.storage.models.vault_models import Chat, ChatRole, CitedClaimNode, InferenceNode, NodeType, TurnNode

client = TestClient(app, client=("127.0.0.1", 12345))


def _chat(slug: str = "test-chat") -> Chat:
    return Chat(slug=slug, title="Test Chat", node_type=NodeType.chat, path=Path(f"/tmp/{slug}.sess"), messages=[])


def _msg(role: ChatRole, text: str, **overrides) -> TurnNode:
    return TurnNode(role=role, content=RichContent(value=text), **overrides)


def test_chat_route_returns_claims_from_assistant_message(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    assistant_msg = _msg(
        ChatRole.assistant, "Kùzu was chosen for its embedded mode[^1].",
        claims=[CitedClaimNode(index=1, claim_text="", relation="attribution", sources=["kg-decision"])],
    )
    chat_agent = MagicMock()
    chat_agent.respond.return_value = assistant_msg
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "why Kùzu?", "chat_slug": "test-chat"})

    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "Kùzu was chosen for its embedded mode[^1]."
    assert len(data["claims"]) == 1
    claim = data["claims"][0]
    assert claim["kind"] == "claim"
    assert claim["index"] == 1
    assert claim["relation"] == "attribution"
    assert claim["sources"] == ["kg-decision"]
    vault.append_messages.assert_called_once()


def test_chat_route_claims_default_to_empty_list(monkeypatch):
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
    assert r.json()["claims"] == []
    assert r.json()["recalls"] == []


def test_chat_route_passes_chat_slug_to_respond(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat(slug="my-chat")
    monkeypatch.setattr(app_module, "_vault", vault)

    chat_agent = MagicMock()
    chat_agent.respond.return_value = _msg(ChatRole.assistant, "A plain answer.")
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    client.post("/chat", json={"message": "hello", "chat_slug": "my-chat"})

    _, call_kwargs = chat_agent.respond.call_args
    assert call_kwargs["chat_slug"] == "my-chat"


def test_chat_route_returns_recalls_from_assistant_message(monkeypatch):
    from prisma.storage.models.vault_models import RecallRef

    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    assistant_msg = _msg(
        ChatRole.assistant, "Recalled that earlier.",
        recalls=[RecallRef(node_id="abc123", node_kind="turn")],
    )
    chat_agent = MagicMock()
    chat_agent.respond.return_value = assistant_msg
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "why?", "chat_slug": "test-chat"})

    assert r.status_code == 200
    assert r.json()["recalls"] == [{"node_id": "abc123", "node_kind": "turn", "chat_slug": None}]


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
        claims=[InferenceNode(index=1, claim_text="")],
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
             claims=[InferenceNode(index=1, claim_text="")]),
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


# ── v3: attachments/attached_slugs flow into the user TurnNode ──────────────

def test_chat_route_passes_attachments_and_attached_slugs_to_user_turn(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    chat_agent = MagicMock()
    chat_agent.respond.return_value = _msg(ChatRole.assistant, "ok")
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={
        "message": "check this diagram against my notes", "chat_slug": "test-chat",
        "attachments": [{"kind": "drawio", "value": "<mxGraphModel/>"}],
        "attached_slugs": ["my-existing-note"],
    })

    assert r.status_code == 200
    user_msg = vault.append_messages.call_args[0][1][0]
    assert user_msg.role == ChatRole.user
    assert user_msg.attachments[0].kind == "drawio"
    assert user_msg.attached_slugs == ["my-existing-note"]


def test_chat_route_attachments_default_to_empty(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.return_value = _chat()
    monkeypatch.setattr(app_module, "_vault", vault)

    chat_agent = MagicMock()
    chat_agent.respond.return_value = _msg(ChatRole.assistant, "ok")
    chat_agent.model = "test-model"
    monkeypatch.setattr(app_module, "_chat_agent", chat_agent)

    r = client.post("/chat", json={"message": "hello", "chat_slug": "test-chat"})

    assert r.status_code == 200
    user_msg = vault.append_messages.call_args[0][1][0]
    assert user_msg.attachments == []
    assert user_msg.attached_slugs == []


# ── POST /chats/{slug}/attachments/upload (jpg only) ─────────────────────────

_JPG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 16


def test_upload_attachment_writes_file_and_returns_asset_media_node(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)

    r = client.post(
        f"/chats/{chat_slug}/attachments/upload",
        files={"file": ("figure.jpg", _JPG_MAGIC, "image/jpeg")},
    )

    assert r.status_code == 201
    attachment = r.json()["attachment"]
    assert attachment["kind"] == "jpg"
    assert attachment["asset_path"].startswith(f"chats/{chat_slug}-attachments/")
    assert (real_vault.root / attachment["asset_path"]).read_bytes() == _JPG_MAGIC


def test_upload_attachment_rejects_non_jpg_bytes(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)

    r = client.post(
        f"/chats/{chat_slug}/attachments/upload",
        files={"file": ("not-a.jpg", b"plain text, not a jpeg", "image/jpeg")},
    )

    assert r.status_code == 400


def test_upload_attachment_404_when_chat_not_found(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.side_effect = FileNotFoundError()
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post(
        "/chats/missing-chat/attachments/upload",
        files={"file": ("figure.jpg", _JPG_MAGIC, "image/jpeg")},
    )

    assert r.status_code == 404


# ── GET /models ───────────────────────────────────────────────────────────

def test_list_models_returns_ollama_tags(monkeypatch):
    from prisma.server import app as app_module
    from prisma.utils.config import ChatConfig, ConfigLoader, LLMConfig

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen2.5:7b-32k"}, {"name": "qwen2.5-3b"}]}

    cfg = MagicMock(spec=ConfigLoader)
    cfg.get_chat_config.return_value = ChatConfig(model="qwen2.5:7b-32k")
    cfg.get_llm_config.return_value = LLMConfig(host="localhost:11434")
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", lambda: cfg)
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

    r = client.get("/models")

    assert r.status_code == 200
    data = r.json()
    assert data["current"] == "qwen2.5:7b-32k"
    assert set(data["models"]) == {"qwen2.5:7b-32k", "qwen2.5-3b"}


def test_list_models_degrades_to_current_only_when_ollama_unreachable(monkeypatch):
    from prisma.server import app as app_module
    from prisma.utils.config import ChatConfig, ConfigLoader, LLMConfig

    def _raise(*a, **k):
        raise ConnectionError("no route to host")

    cfg = MagicMock(spec=ConfigLoader)
    cfg.get_chat_config.return_value = ChatConfig(model="qwen2.5:7b-32k")
    cfg.get_llm_config.return_value = LLMConfig(host="localhost:11434")
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", lambda: cfg)
    monkeypatch.setattr("requests.get", _raise)

    r = client.get("/models")

    assert r.status_code == 200
    assert r.json() == {"models": ["qwen2.5:7b-32k"], "current": "qwen2.5:7b-32k"}


def test_list_models_returns_llama_swap_openai_models(monkeypatch):
    # llama_cpp here means llama-swap (/opt/llama-swap) -- OpenAI-compatible
    # /v1/models ({"data": [{"id": ...}]}), NOT Ollama's /api/tags shape.
    # Found live: querying /api/tags against llama-swap 404s, silently
    # degrading to a single-model list that hides the picker entirely.
    from prisma.server import app as app_module
    from prisma.utils.config import ChatConfig, ConfigLoader, LLMConfig

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "qwen2.5-3b"}, {"id": "bge-m3"}], "object": "list"}

    cfg = MagicMock(spec=ConfigLoader)
    cfg.get_chat_config.return_value = ChatConfig(provider="llama_cpp", model="qwen2.5-3b")
    cfg.get_llm_config.return_value = LLMConfig(host="localhost:8090")
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", lambda: cfg)
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

    r = client.get("/models")

    assert r.status_code == 200
    data = r.json()
    assert data["current"] == "qwen2.5-3b"
    assert set(data["models"]) == {"qwen2.5-3b", "bge-m3"}


def test_list_models_degrades_to_current_only_when_llama_swap_unreachable(monkeypatch):
    from prisma.server import app as app_module
    from prisma.utils.config import ChatConfig, ConfigLoader, LLMConfig

    def _raise(*a, **k):
        raise ConnectionError("no route to host")

    cfg = MagicMock(spec=ConfigLoader)
    cfg.get_chat_config.return_value = ChatConfig(provider="llama_cpp", model="qwen2.5-3b")
    cfg.get_llm_config.return_value = LLMConfig(host="localhost:8090")
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", lambda: cfg)
    monkeypatch.setattr("requests.get", _raise)

    r = client.get("/models")

    assert r.status_code == 200
    assert r.json() == {"models": ["qwen2.5-3b"], "current": "qwen2.5-3b"}


# ── POST /chats/{slug}/attachments/promote ───────────────────────────────────

def test_promote_asset_media_node_copies_file_and_returns_note_slug(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)
    indexer = MagicMock()
    monkeypatch.setattr(app_module, "_indexer", indexer)
    upload = client.post(
        f"/chats/{chat_slug}/attachments/upload",
        files={"file": ("figure.jpg", _JPG_MAGIC, "image/jpeg")},
    )

    r = client.post(f"/chats/{chat_slug}/attachments/promote", json={
        "attachment": upload.json()["attachment"], "title": "My Figure",
    })

    assert r.status_code == 201
    slug = r.json()["slug"]
    note = real_vault.get_note(slug)
    assert note.title == "My Figure"
    assert note.original_ext == ".jpg"
    indexer.mark_stale.assert_called_once()


def test_promote_inline_media_node_writes_companion_text(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)
    monkeypatch.setattr(app_module, "_indexer", MagicMock())

    r = client.post(f"/chats/{chat_slug}/attachments/promote", json={
        "attachment": {"kind": "drawio", "value": "<mxGraphModel/>"},
    })

    assert r.status_code == 201
    note = real_vault.get_note(r.json()["slug"])
    assert note.original_ext == ".drawio"
    companion = real_vault.find_companion(note.slug)
    assert companion.read_text(encoding="utf-8") == "<mxGraphModel/>"


def test_promote_pdf_attachment_generates_real_md_body(monkeypatch, tmp_path):
    from prisma.server import app as app_module

    real_vault = VaultService(vault_root=tmp_path / "vault")
    real_vault.ensure_dirs()
    chat_slug = real_vault.create_chat(title="Test Chat").slug
    monkeypatch.setattr(app_module, "_vault", real_vault)
    monkeypatch.setattr(app_module, "_indexer", MagicMock())
    monkeypatch.setattr("prisma.services.vault.pdf_bytes_to_md", lambda data: "Extracted PDF text.")

    upload = client.post(
        f"/chats/{chat_slug}/attachments/upload",
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    r = client.post(f"/chats/{chat_slug}/attachments/promote", json={
        "attachment": upload.json()["attachment"],
    })

    assert r.status_code == 201
    note = real_vault.get_note(r.json()["slug"])
    assert note.body == "Extracted PDF text."


def test_promote_attachment_404_when_chat_not_found(monkeypatch):
    from prisma.server import app as app_module

    vault = MagicMock()
    vault.get_chat.side_effect = FileNotFoundError()
    monkeypatch.setattr(app_module, "_vault", vault)

    r = client.post("/chats/missing-chat/attachments/promote", json={
        "attachment": {"kind": "svg", "value": "<svg/>"},
    })

    assert r.status_code == 404


def test_list_models_degrades_for_non_ollama_provider(monkeypatch):
    from prisma.server import app as app_module
    from prisma.utils.config import ChatConfig, ConfigLoader, LLMConfig

    cfg = MagicMock(spec=ConfigLoader)
    cfg.get_chat_config.return_value = ChatConfig(provider="openrouter", model="claude-opus")
    cfg.get_llm_config.return_value = LLMConfig()
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", lambda: cfg)

    r = client.get("/models")

    assert r.status_code == 200
    assert r.json() == {"models": ["claude-opus"], "current": "claude-opus"}


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
