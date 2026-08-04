# Deployment Models

Prisma supports three deployment configurations. Security requirements, TLS, and
authentication are enforced automatically based on the client's source IP — the server
detects which zone a connection comes from and applies the appropriate auth level.

---

## Zones

The server classifies every incoming connection into one of three zones:

| Zone | Client IP | Auth | TLS |
|---|---|---|---|
| Local | `127.0.0.1` / `::1` | None | Not needed |
| LAN | RFC1918 range (`10.x`, `172.16-31.x`, `192.168.x`) | Password | Optional |
| WAN | Everything else | OIDC | Required |

Zone detection happens in middleware before any route handler runs. A public IP that
somehow reaches the server without passing through a reverse proxy is rejected if OIDC
is not configured.

When a reverse proxy (Caddy) is in front, the server trusts `X-Forwarded-For` **only
when the direct connection comes from loopback** — the proxy's address. This prevents
IP spoofing from direct connections.

---

## Model 1 — Local (development)

Server and client on the same machine. Loopback only.

```
┌─────────────────────────────────┐
│  Linux / WSL2                   │
│  prisma serve → 127.0.0.1:8765  │
│  Browser / Tauri → /app         │
└─────────────────────────────────┘
```

Zone detected: **local** → no auth, no TLS.

PWA service workers work on `localhost` without HTTPS (browser exception for loopback).

---

## Model 2 — LAN server (primary setup)

Server on a dedicated machine (mini PC, NAS, etc.) on the home network.
Clients connect from the same LAN — desktop browser, Tauri shell, mobile PWA.

```
┌─────────────────────────────────────────────────────┐
│  Home network (192.168.x.0/24)                      │
│                                                     │
│  [Mini PC]  prisma serve → 0.0.0.0:8765             │
│                  ↑                                  │
│  [Laptop / Tauri]   192.168.x.y → LAN zone          │
│  [Phone / PWA]      192.168.x.z → LAN zone          │
└─────────────────────────────────────────────────────┘
```

Zone detected: **LAN** → password auth.

⚠️ PWA service workers require HTTPS on non-localhost origins. On plain HTTP LAN the
app works but the service worker (offline cache) is disabled. For full PWA on LAN,
run Caddy with a local cert or access via the WAN URL (Model 3).

---

## Model 3 — Internet-facing (WAN)

Server accessible from anywhere via a public hostname. Two variants:

**3a — Home server with DynaDNS or static IP**
```
Internet
  │
  ▼
Router (port-forward 443 → mini-pc:8765)
  │
  ▼
[Mini PC]  Caddy → TLS → localhost:8765
  │
  └── prisma.yourdomain.com
```

**3b — Cloud VPS (Hetzner, DigitalOcean, etc.)**
```
Internet
  │
  ▼
[VPS: Ubuntu]
  Caddy → TLS → localhost:8765
  prisma.yourdomain.com
```

Zone detected: **WAN** (via `X-Forwarded-For` from Caddy) → OIDC auth + HTTPS required.

All three client types (local browser, Tauri, mobile PWA) work against the WAN URL.
Tauri stores the server URL in settings — point it to `https://prisma.yourdomain.com`
when away from home.

---

## Container image (Kubernetes / any OCI runtime)

`ghcr.io/cservinl/prisma:<tag>` — built and published automatically by
`.github/workflows/build-image.yml` on every push to `main`, via Podman/buildah
(daemonless, rootless — no Docker Desktop, no root daemon on the build runner).
Tags: `latest`, the repo-root `VERSION` file's contents (single source of
truth — `pyproject.toml` reads its own `version` from the same file via
`[tool.setuptools.dynamic]`), and the commit SHA.

The `ui-build` stage is the *only* place node/npm ever runs — the compiled
SvelteKit output is baked into the final image as static files (served at
`/app`). A server never compiles anything; there is no build step at
deploy/runtime, unlike this repo's own "dev mode" Helm chart pattern
(`CServinL/charts/charts/prisma-dev`), which instead git-clones and
`pip install -e`s on every pod start and has no image build at all. Bumping
`VERSION` and merging to `main` is what produces a new pinned tag for a chart
to move to — `:latest` always exists too, for anyone who wants to float.

---

## Recommended reverse proxy: Caddy

Caddy handles TLS automatically (Let's Encrypt). No manual cert management.

```
# /etc/caddy/Caddyfile
prisma.yourdomain.com {
    reverse_proxy localhost:8765
}
```

Install: `apt install caddy` or `brew install caddy`.

---

## Configuration

`~/.config/prisma/config.toml`:

```toml
[server]
host = "0.0.0.0"   # "127.0.0.1" for local-only (Model 1)
port = 8765
trusted_proxies = ["127.0.0.1", "::1"]   # IPs allowed to set X-Forwarded-For (default: loopback only)

[server.auth]
# LAN zone — password
password_hash = ""   # bcrypt hash — generate: prisma auth hash-password

# WAN zone — OIDC (any compliant provider) — not implemented yet, see ADR-011
oidc_issuer = ""     # e.g. https://accounts.google.com
client_id = ""       #      or https://your-org.zitadel.cloud
client_secret = ""   #      or https://auth.yourdomain.com/application/o/prisma/
allowed_emails = []  # restrict to specific accounts (required for Google)
```

Generate a bcrypt password hash:
```bash
prisma auth hash-password
```

---

## OIDC providers (WAN zone)

Any OIDC-compliant provider works. Common options:

| Provider | Type | Notes |
|---|---|---|
| **Zitadel cloud** (zitadel.com) | Hosted SaaS | Free tier, self-hosteable if needed |
| **Google Identity** | Hosted SaaS | Free, requires `allowed_emails` |
| **Authentik** | Self-hosted | Full control, Docker-based |
| Auth0, Okta, Cognito | Hosted SaaS | Paid tiers |

Provider discovery is automatic via `{oidc_issuer}/.well-known/openid-configuration` —
no per-provider code in Prisma.
