"""Server-side authentication — ADR-011, password mode only.

Zone-based gating (see docs/wiki/deployment-models.md): the `local` zone
(loopback) never needs auth; the `lan` zone (RFC1918) requires a valid
session token whenever `server.auth.mode: password`; the `wan` zone is
always rejected — `mode: oidc` is documented for a future WAN tier but is
rejected at config-load time (utils/config.py) since it isn't implemented.

Pure ASGI middleware, not `BaseHTTPMiddleware`: the latter only sees the
`"http"` scope, but the `/ws` upgrade needs the exact same zone gating.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from typing import Literal

import bcrypt
import jwt
from pydantic import BaseModel

from prisma.utils.config import ConfigLoader

Zone = Literal["local", "lan", "wan"]

# /auth/login must stay reachable with no token yet (chicken-and-egg); /health
# is a plain liveness probe with no sensitive content — both predate auth.
_EXEMPT_PATHS = {"/health", "/auth/login"}
_ALGO = "HS256"


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


# ── password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ── session tokens ────────────────────────────────────────────────────────────

def _signing_key(password_hash: str) -> bytes:
    # Derived from the password hash rather than a separately stored secret —
    # rotating the password invalidates every outstanding session for free,
    # with no extra secret to generate, persist, or leak.
    return hashlib.sha256(password_hash.encode("utf-8")).digest()


def issue_token(password_hash: str, ttl_hours: int) -> tuple[str, float]:
    """Returns (token, expires_at_epoch_seconds)."""
    now = time.time()
    exp = now + ttl_hours * 3600
    token = jwt.encode({"iat": now, "exp": exp}, _signing_key(password_hash), algorithm=_ALGO)
    return token, exp


def decode_token(token: str, password_hash: str) -> dict | None:
    try:
        return jwt.decode(token, _signing_key(password_hash), algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None


# ── zone classification ───────────────────────────────────────────────────────

def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _is_private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback


def classify_zone(direct_host: str, forwarded_for: str | None, trusted_proxies: list[str]) -> Zone:
    """`direct_host` is the actual TCP peer (`scope['client'][0]`).
    `X-Forwarded-For` is honored only when the direct connection itself
    comes from a trusted proxy address — otherwise a WAN client could just
    set the header itself to spoof a local/LAN origin."""
    candidate = direct_host
    if forwarded_for and direct_host in trusted_proxies:
        candidate = forwarded_for.split(",")[0].strip()
    if _is_loopback(candidate):
        return "local"
    if _is_private(candidate):
        return "lan"
    return "wan"


# ── ASGI middleware ────────────────────────────────────────────────────────────

def _get_header(scope: dict, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _bearer_from_http(scope: dict) -> str | None:
    auth = _get_header(scope, b"authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _bearer_from_ws(scope: dict) -> str | None:
    # Browsers can't set custom headers on a WS handshake but can set
    # subprotocols — the client sends ["bearer", "<jwt>"] and the endpoint
    # itself must echo one of the offered values via accept(subprotocol=...).
    raw = _get_header(scope, b"sec-websocket-protocol")
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 2 and parts[0] == "bearer":
        return parts[1]
    return None


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        server_cfg = ConfigLoader().get_server_config()
        auth_cfg = server_cfg.auth
        client = scope.get("client")
        direct_host = client[0] if client else "127.0.0.1"
        forwarded_for = _get_header(scope, b"x-forwarded-for")
        zone = classify_zone(direct_host, forwarded_for, server_cfg.trusted_proxies)

        if zone == "wan":
            await self._reject(scope, send, 403, "wan access is not permitted (oidc mode not implemented)")
            return

        if zone == "local" or auth_cfg.mode == "none":
            await self.app(scope, receive, send)
            return

        # zone == "lan" and mode == "password" — "oidc" is rejected at
        # config-load time, so this is the only remaining combination.
        token = _bearer_from_http(scope) if scope["type"] == "http" else _bearer_from_ws(scope)
        if not token or decode_token(token, auth_cfg.password_hash) is None:
            await self._reject(scope, send, 401, "authentication required")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            return
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})
