"""Unit tests for GET/PUT /chat/system-prompt -- the Settings page's "Chat
instructions" panel backing routes. Wraps chat_prompts.py's
load_system_prompt/save_system_prompt; PUT also triggers _reload_chat so the
running ChatAgent picks up the edit without a full restart.
"""
from fastapi.testclient import TestClient

from prisma.server.app import app

client = TestClient(app, client=("127.0.0.1", 12345))


def test_get_chat_system_prompt_returns_current_content(monkeypatch):
    from prisma.server import app as app_module

    monkeypatch.setattr(app_module, "load_system_prompt", lambda: "You are Prisma.")

    r = client.get("/chat/system-prompt")

    assert r.status_code == 200
    assert r.json() == {"content": "You are Prisma."}


def test_put_chat_system_prompt_saves_and_reloads(monkeypatch):
    from prisma.server import app as app_module

    saved = {}
    monkeypatch.setattr(app_module, "save_system_prompt", lambda content: saved.setdefault("content", content))
    monkeypatch.setattr(app_module, "load_system_prompt", lambda: saved.get("content", ""))
    reload_calls = []
    monkeypatch.setattr(app_module, "_reload_chat", lambda *a, **kw: reload_calls.append(1))

    r = client.put("/chat/system-prompt", json={"content": "Always answer in Spanish."})

    assert r.status_code == 200
    assert r.json() == {"content": "Always answer in Spanish."}
    assert saved["content"] == "Always answer in Spanish."
    assert reload_calls == [1]
