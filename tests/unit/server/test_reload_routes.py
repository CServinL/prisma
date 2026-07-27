"""Unit tests for app.py's reload routes — the smart POST /reload (backs
`prisma reload-config`) and the new POST /reload/chat gap-fill.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from prisma.server.app import app
from prisma.utils.config import PrismaConfig

client = TestClient(app, client=("127.0.0.1", 12345))


def _fake_resources_ok(*a, **kw):
    return {"status": "reloaded", "pools": ["default"]}


def _fake_resources_unreachable(*a, **kw):
    return {"error": "connection refused"}


def test_reload_chat_rebuilds_chat_agent(monkeypatch):
    from prisma.server import app as app_module

    calls = []
    monkeypatch.setattr(app_module, "_build_chat_agent", lambda *a, **kw: calls.append(1) or "agent")

    r = client.post("/reload/chat")
    assert r.status_code == 200
    assert calls == [1]
    assert app_module._chat_agent == "agent"


def test_reload_invalid_config_returns_422_and_leaves_active_config(monkeypatch):
    from prisma.server import app as app_module

    class _BrokenLoader:
        def __init__(self, *a, **kw):
            raise ValueError("bad yaml")

    before = app_module._active_config
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", _BrokenLoader)

    r = client.post("/reload")
    assert r.status_code == 422
    assert app_module._active_config is before


def test_reload_no_changes_reports_empty(monkeypatch):
    from prisma.server import app as app_module

    class _SameLoader:
        def __init__(self, *a, **kw):
            self.config = app_module._active_config

    monkeypatch.setattr("prisma.utils.config.ConfigLoader", _SameLoader)
    monkeypatch.setattr(
        "prisma.services.resource_lock.reload_resources", _fake_resources_ok
    )

    r = client.post("/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] == []
    assert body["reloaded"] == []
    assert body["compute_pools_reloaded"] is True


def test_reload_single_section_change_calls_only_that_helper(monkeypatch):
    from prisma.server import app as app_module

    new_config = app_module._active_config.model_copy(update={"vault_root": "/tmp/other-vault"})

    class _ChangedLoader:
        def __init__(self, *a, **kw):
            self.config = new_config

    calls = {"vault": 0, "zotero": 0, "chroma": 0, "chat": 0}
    monkeypatch.setattr("prisma.utils.config.ConfigLoader", _ChangedLoader)
    monkeypatch.setattr(app_module, "_reload_vault", lambda *a, **kw: calls.__setitem__("vault", calls["vault"] + 1))
    monkeypatch.setattr(app_module, "_reload_zotero", lambda *a, **kw: calls.__setitem__("zotero", calls["zotero"] + 1))
    monkeypatch.setattr(app_module, "_reload_chroma", lambda *a, **kw: calls.__setitem__("chroma", calls["chroma"] + 1))
    monkeypatch.setattr(app_module, "_reload_chat", lambda *a, **kw: calls.__setitem__("chat", calls["chat"] + 1))
    monkeypatch.setitem(app_module._RELOAD_FNS, "vault_root", app_module._reload_vault)
    monkeypatch.setattr(
        "prisma.services.resource_lock.reload_resources", _fake_resources_ok
    )

    r = client.post("/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] == ["vault_root"]
    assert body["reloaded"] == ["vault_root"]
    assert calls == {"vault": 1, "zotero": 0, "chroma": 0, "chat": 0}


def test_reload_supervisor_unreachable_reports_false(monkeypatch):
    from prisma.server import app as app_module

    class _SameLoader:
        def __init__(self, *a, **kw):
            self.config = app_module._active_config

    monkeypatch.setattr("prisma.utils.config.ConfigLoader", _SameLoader)
    monkeypatch.setattr(
        "prisma.services.resource_lock.reload_resources", _fake_resources_unreachable
    )

    r = client.post("/reload")
    assert r.status_code == 200
    assert r.json()["compute_pools_reloaded"] is False
