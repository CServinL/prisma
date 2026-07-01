# ADR-010: Transport Layer Strategy — REST + WebSocket

**Date:** 2026-06-30
**Author:** CServinL
**Status:** Accepted

## Context

Prisma is evolving from a CLI tool into a server-first application with a SvelteKit PWA UI
targeting Linux (Tauri shell), Android, iOS, and macOS (browser PWA). This shift introduces
two new transport requirements:

1. **Server push**: the server needs to notify clients of vault changes, stream update progress,
   and UI hot-reload signals without the client polling.
2. **Streaming responses**: LLM chat answers should stream token-by-token rather than block
   until the full response is ready.

The existing API is REST over HTTP. The question is how much of it, if any, should migrate
to WebSocket.

## Decision

Keep REST as the primary transport. Add a single WebSocket channel (`/ws`) for use cases
where WebSocket provides a concrete, non-theoretical advantage. REST remains the fallback
when WebSocket is unavailable.

The split is:

| Transport | Used for |
|-----------|----------|
| REST (HTTP) | All CRUD endpoints: notes, tree, streams, search, status, Zotero, vault assets, binary file upload/download |
| WebSocket (`/ws`) | Server push events (vault changes, stream progress, hot-reload), streaming LLM responses |

Static files, binary responses (vault assets, file downloads), and file uploads stay on HTTP
in both directions. These are served by standard HTTP machinery (range requests, content-type
negotiation, browser caching) that WebSocket cannot replicate.

### Why not full REST → WebSocket migration?

For Prisma's deployment profile (single process, localhost or LAN, one client, no CDN) most
theoretical REST advantages don't apply in practice. The one that does: **tooling**. Losing
`curl /notes` is a real, recurring cost during development and debugging. Keeping REST means
every API endpoint remains directly inspectable without a custom client.

API responses in Prisma are highly personalized (vault-specific data, user config, local model
outputs) and never shared between users. HTTP caching and CDN distribution, the primary REST
advantages at scale, provide no benefit here.

### Why not WebSocket everywhere?

WebSocket is blocked or degraded by some corporate proxies, VPNs, and mobile network
middleboxes. For a PWA targeting Android and iOS on arbitrary networks, this is a real
failure mode. REST over HTTPS passes through every network configuration that supports
HTTPS at all.

Streaming and push are the two cases where maintaining an open connection is the only
reasonable model. For standard request/response operations (read a note, list streams, run
a search), REST is simpler to implement, simpler to debug, and semantically clearer.

### WebSocket message protocol

All WebSocket messages are JSON with a `type` field:

**Server → client push events:**
```json
{ "type": "vault_change", "path": "notes/slug.md" }
{ "type": "stream_progress", "slug": "...", "status": "running", "found": 12 }
{ "type": "hot_reload", "version": 7 }
{ "type": "chat_token", "request_id": "...", "token": "..." }
{ "type": "chat_done", "request_id": "..." }
```

**Client → server (streaming requests only):**
```json
{ "type": "chat", "request_id": "...", "prompt": "...", "context_slugs": ["..."] }
```

Non-streaming requests (notes, search, tree, etc.) continue to use `fetch()` against the
existing REST endpoints.

### REST fallback

The client checks WebSocket availability on startup. If the connection fails or is
unavailable:
- Push events: degraded gracefully (no live updates; user refreshes manually)
- Streaming LLM: falls back to a single blocking REST call (`POST /chat`) that returns
  the full response when complete

## Alternatives Considered

### Full migration to WebSocket

Rejected. Would eliminate `curl`-ability of the API with no benefit beyond a unified
connection model. Existing REST endpoints are already simple and well-tested. The migration
cost is not justified when WebSocket is only needed for push and streaming.

### Server-Sent Events (SSE) instead of WebSocket

Considered for the push-only case. SSE is simpler (plain HTTP, no upgrade handshake, works
through more proxies) and sufficient for server → client push. Rejected because SSE cannot
carry bidirectional messages — streaming LLM chat requires the client to initiate a streaming
request and the server to respond on the same channel. Using both SSE and a separate streaming
endpoint would be more complex than a single WebSocket channel.

### GraphQL subscriptions

Rejected. GraphQL adds a schema layer and resolver infrastructure that would require
rewriting all existing endpoints. The subscription mechanism solves the same problem as
WebSocket push but with significantly more setup. At single-client scale with a stable API
shape, the schema flexibility GraphQL provides has no value.

### Polling (status quo)

The hot-reload signal currently uses polling (`GET /ui/dev/version` every 2 s). Acceptable
for dev, but polling for vault changes and stream progress would generate unnecessary load
and add latency. Push replaces polling for all live-update use cases.

## Consequences

### Positive

- REST API unchanged — all existing endpoints, tests, and `curl` workflows remain valid
- WebSocket adds push and streaming without touching the existing surface
- PWA on Android/iOS gets live updates where network permits, degrades cleanly where it doesn't
- Single `/ws` endpoint is easy to reason about and test

### Negative

- Two transport layers to maintain; contributors must know which layer a new feature belongs on
- WebSocket reconnect logic needed on the client (exponential backoff, re-subscribe on reconnect)
- Streaming LLM fallback (`POST /chat`) must be kept in sync with the WS streaming path

## Related ADRs

- ADR-001: Pipeline Architecture (LLM calls flow through agents; streaming wraps the same calls)
- ADR-009: Hybrid Retrieval (search results are candidates for WS streaming in future)
