"""Unit tests for prisma.server.auth — zone classification, password hashing,
session tokens, and the AuthMiddleware's zone/mode gating (ADR-011).
"""
import os

import pytest
from fastapi.testclient import TestClient

from prisma.server.auth import (
    classify_zone,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)

_TRUSTED = ["127.0.0.1", "::1"]


# ── classify_zone (pure function) ─────────────────────────────────────────────

def test_classify_zone_loopback():
    assert classify_zone("127.0.0.1", None, _TRUSTED) == "local"
    assert classify_zone("::1", None, _TRUSTED) == "local"
    assert classify_zone("localhost", None, _TRUSTED) == "local"


def test_classify_zone_lan():
    assert classify_zone("192.168.1.50", None, _TRUSTED) == "lan"
    assert classify_zone("10.0.0.5", None, _TRUSTED) == "lan"
    assert classify_zone("172.16.0.5", None, _TRUSTED) == "lan"


def test_classify_zone_wan():
    assert classify_zone("8.8.8.8", None, _TRUSTED) == "wan"


def test_classify_zone_trusts_forwarded_for_only_from_trusted_proxy():
    # Direct connection from the trusted proxy (loopback) — header honored.
    assert classify_zone("127.0.0.1", "192.168.1.50", _TRUSTED) == "lan"
    # Direct connection NOT from a trusted proxy — header must be ignored,
    # otherwise a WAN client could spoof a local/LAN origin by setting it.
    assert classify_zone("8.8.8.8", "127.0.0.1", _TRUSTED) == "wan"


# ── password hashing ──────────────────────────────────────────────────────────

def test_hash_and_verify_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_verify_password_empty_hash_always_fails():
    assert not verify_password("anything", "")


# ── session tokens ────────────────────────────────────────────────────────────

def test_issue_and_decode_token_roundtrip():
    pw_hash = hash_password("hunter2")
    token, expires_at = issue_token(pw_hash, ttl_hours=1)
    payload = decode_token(token, pw_hash)
    assert payload is not None
    assert payload["exp"] == pytest.approx(expires_at)


def test_decode_token_rejects_wrong_password_hash():
    pw_hash = hash_password("hunter2")
    other_hash = hash_password("different password")
    token, _ = issue_token(pw_hash, ttl_hours=1)
    assert decode_token(token, other_hash) is None


def test_decode_token_rejects_expired_token():
    pw_hash = hash_password("hunter2")
    token, _ = issue_token(pw_hash, ttl_hours=-1)  # already expired
    assert decode_token(token, pw_hash) is None


def test_decode_token_rejects_garbage():
    pw_hash = hash_password("hunter2")
    assert decode_token("not-a-jwt", pw_hash) is None


# ── AuthMiddleware, end-to-end via TestClient ─────────────────────────────────

@pytest.fixture
def password_mode_config(tmp_path, monkeypatch):
    pw_hash = hash_password("s3cret")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "server:\n"
        "  auth:\n"
        "    mode: password\n"
        f"    password_hash: '{pw_hash}'\n"
    )
    monkeypatch.setenv("PRISMA_CONFIG", str(cfg_path))
    return pw_hash


def _client_from(host: str) -> TestClient:
    # `client` is a TestClient *constructor* kwarg (the simulated TCP peer
    # address for scope['client']) — it can't be mutated on an existing
    # instance, a fresh TestClient is needed per simulated source zone.
    from prisma.server.app import app
    return TestClient(app, client=(host, 12345))


def test_local_zone_bypasses_auth_even_in_password_mode(password_mode_config):
    r = _client_from("127.0.0.1").get("/status")
    assert r.status_code == 200


def test_lan_zone_requires_token_in_password_mode(password_mode_config):
    r = _client_from("192.168.1.50").get("/status")
    assert r.status_code == 401


def test_lan_zone_passes_with_valid_token(password_mode_config):
    client = _client_from("192.168.1.50")
    r = client.post("/auth/login", json={"password": "s3cret"})
    assert r.status_code == 200
    token = r.json()["token"]

    r2 = client.get("/status", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_login_rejects_wrong_password(password_mode_config):
    r = _client_from("192.168.1.50").post("/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_wan_zone_always_rejected(password_mode_config):
    r = _client_from("8.8.8.8").get("/status")
    assert r.status_code == 403


def test_login_rejected_from_wan_zone(password_mode_config):
    r = _client_from("8.8.8.8").post("/auth/login", json={"password": "s3cret"})
    assert r.status_code == 403


def test_health_always_reachable_regardless_of_zone(password_mode_config):
    r = _client_from("8.8.8.8").get("/health")
    assert r.status_code == 200


# ── /ws upgrade gating ─────────────────────────────────────────────────────────

def test_ws_lan_zone_rejected_without_token(password_mode_config):
    client = _client_from("192.168.1.50")
    with pytest.raises(Exception):
        with client.websocket_connect("/ws"):
            pass


def test_ws_lan_zone_accepted_with_valid_subprotocol_token(password_mode_config):
    client = _client_from("192.168.1.50")
    login = client.post("/auth/login", json={"password": "s3cret"})
    token = login.json()["token"]
    with client.websocket_connect("/ws", subprotocols=["bearer", token]):
        pass  # connecting without raising is the assertion


def test_ws_local_zone_accepted_without_token_even_in_password_mode(password_mode_config):
    client = _client_from("127.0.0.1")
    with client.websocket_connect("/ws"):
        pass


def test_mode_none_bypasses_auth_from_any_zone(monkeypatch, tmp_path):
    # Point at a nonexistent path rather than just delenv — a real
    # ~/.config/prisma/config.yaml on the machine running this test would
    # otherwise be picked up by ConfigLoader's default-locations fallback
    # (a real footgun found earlier in this project: see test_config.py).
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "does-not-exist.yaml"))
    r = _client_from("192.168.1.50").get("/status")
    assert r.status_code == 200
