"""Unit tests for GET/PUT /chat/user-prompt -- the Settings page's "Chat
instructions" panel backing routes. Wraps chat_prompts.py's
load_user_prompt/save_user_prompt (the user's additive layer only -- the
fixed base system prompt is not exposed here); PUT also triggers
_reload_chat so the running ChatAgent picks up the edit without a full
restart.
"""
from fastapi.testclient import TestClient

from prisma.server.app import app

client = TestClient(app, client=("127.0.0.1", 12345))


def test_get_chat_user_prompt_returns_current_content(monkeypatch):
    from prisma.server import app as app_module

    monkeypatch.setattr(app_module, "load_user_prompt", lambda: "Always cite page numbers when quoting a PDF.")

    r = client.get("/chat/user-prompt")

    assert r.status_code == 200
    assert r.json() == {"content": "Always cite page numbers when quoting a PDF."}


def test_put_chat_user_prompt_saves_and_reloads(monkeypatch):
    from prisma.server import app as app_module

    saved = {}
    monkeypatch.setattr(app_module, "save_user_prompt", lambda content: saved.setdefault("content", content))
    monkeypatch.setattr(app_module, "load_user_prompt", lambda: saved.get("content", ""))
    reload_calls = []
    monkeypatch.setattr(app_module, "_reload_chat", lambda *a, **kw: reload_calls.append(1))

    r = client.put("/chat/user-prompt", json={"content": "Always cite page numbers when quoting a PDF."})

    assert r.status_code == 200
    assert r.json() == {"content": "Always cite page numbers when quoting a PDF."}
    assert saved["content"] == "Always cite page numbers when quoting a PDF."
    assert reload_calls == [1]
