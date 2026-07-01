# ADR-011: Authentication Strategy

**Date:** 2026-06-30
**Author:** CServinL
**Status:** Accepted

## Context

Prisma supports four deployment models (see [deployment-models.md](../deployment-models.md)).
The security requirements differ significantly between them:

- **Local (loopback):** no network exposure — authentication adds friction with zero benefit
- **LAN / offline:** the server is reachable by other devices on the network but may have
  no internet access — needs something that works without external services
- **Internet-facing (DynaDNS, cloud VPS):** publicly reachable — requires strong,
  production-grade authentication

A single auth mechanism cannot serve all three models well.

## Decision

Tiered authentication, configured per deployment:

| Deployment | Auth mode | Mechanism |
|---|---|---|
| Local (loopback) | `none` | No auth — loopback is inherently isolated |
| LAN / offline | `password` | Single shared password, bcrypt-hashed in config |
| Internet-facing | `oidc` | Standard OIDC Authorization Code + PKCE |

The mode is set in `~/.config/prisma/config.yaml` under `server.auth.mode`.
If omitted, defaults to `none`.

### OIDC mode — any compliant provider

When `mode: oidc`, Prisma performs standard OIDC Authorization Code + PKCE against
any compliant provider. The provider is selected by the user via `oidc_issuer` in
config — Prisma contains no provider-specific logic.

Supported providers (non-exhaustive — any OIDC-compliant IdP works):

| Provider | Type | Cost | Offline |
|---|---|---|---|
| Zitadel cloud (zitadel.com) | Hosted SaaS | Free tier (25k MAU) | No |
| Zitadel self-hosted | Self-hosted | Free, open source | Yes |
| Google Identity | Hosted SaaS | Free (personal use) | No |
| Authentik | Self-hosted | Free, open source | Yes |
| Auth0, Okta, Cognito | Hosted SaaS | Paid tiers | No |

Prisma discovers provider endpoints automatically via the standard
`/.well-known/openid-configuration` document — no per-provider configuration is needed
beyond `oidc_issuer` and `client_id`.

For deployments that require internet independence (self-hosted LAN with OIDC), Zitadel
or Authentik self-hosted are the recommended options since they run on the same local
infrastructure as Prisma.

### Password mode

A single bcrypt-hashed password stored in config. The client POSTs to `POST /auth/login`,
receives a signed JWT session token, and sends it as `Authorization: Bearer <token>` on
subsequent requests. Works fully offline. Intended for LAN deployments where OIDC is
not practical.

### OIDC flow (Authorization Code + PKCE)

```
Client (browser/PWA)
  │
  │  1. GET /app  (not authenticated)
  │  ← redirect to /auth/login
  │
  │  2. GET /auth/login
  │  ← redirect to {oidc_issuer}/authorize?response_type=code&client_id=...&code_challenge=...
  │
  │  3. User logs in at provider
  │  ← redirect to /auth/callback?code=...
  │
  │  4. Server exchanges code for ID token (server-to-provider, never exposed to browser)
  │     Server validates: signature, issuer, audience, expiry
  │     Server checks email/sub against allowed_emails list in config
  │
  │  5. Server issues signed session JWT → stored in HttpOnly cookie
  │
  │  6. All subsequent requests + WS upgrade authenticated via cookie
```

PKCE (Proof Key for Code Exchange) is used even though the server handles the code
exchange — it prevents authorization code interception attacks.

### Allowed emails / subjects

For OIDC, an `allowed_emails` list in config restricts access to specific accounts.
This is required for providers like Google where any Google account could otherwise
authenticate against the client ID.

```yaml
server:
  auth:
    mode: oidc
    oidc_issuer: "https://your-org.zitadel.cloud"
    client_id: "..."
    client_secret: "..."
    allowed_emails:
      - "you@gmail.com"
      - "collaborator@domain.com"
```

## Configuration reference

```yaml
server:
  host: "127.0.0.1"   # loopback for Model 1; "0.0.0.0" for Models 2-4
  port: 8765
  auth:
    mode: "none"       # none | password | oidc

    # password mode
    password_hash: ""  # bcrypt hash — generate with: prisma auth hash-password

    # oidc mode
    oidc_issuer: ""    # e.g. https://accounts.google.com or https://org.zitadel.cloud
    client_id: ""
    client_secret: ""
    allowed_emails: []
```

## Alternatives Considered

### Single bearer token (shared secret)

Simple — one random string in config, sent as a header. Rejected as the primary
mechanism because it has no user identity (no audit trail, no MFA, no revocation),
and managing rotation is manual. Kept as a fallback for programmatic API access
(scripts, CLI tools) via `X-API-Key` header alongside session auth.

### Hardcoding a specific OIDC provider

Rejected. Prisma is a personal tool used across diverse setups. Forcing a specific
provider (even a free one) would exclude users who already have Google, an existing
Authentik instance, a corporate Okta, etc. Standard OIDC gives each user the
provider that best fits their infrastructure.

### No auth at all, rely on network-level controls (VPN, firewall)

Valid for many personal setups. The `mode: none` option explicitly supports this.
For users comfortable with network-level isolation (Tailscale, WireGuard, firewall
allowlist), auth at the application layer is optional.

## Consequences

### Positive

- Each deployment model has auth complexity proportional to its threat surface
- OIDC supports Google, Zitadel, Authentik, Auth0, Okta, Cognito without any code change
- Offline-capable deployments (LAN) don't require internet for authentication
- Users who prefer network-level security (VPN/firewall) can opt out entirely

### Negative

- Three auth modes to implement and test
- OIDC requires HTTPS (callback must be on a trusted origin) — not viable for plain HTTP LAN
- `client_secret` in config must be protected (file permissions `600`)

## Related ADRs

- ADR-010: Transport Layer Strategy (WS upgrade must also be authenticated)
- [deployment-models.md](../deployment-models.md): full topology for each model
