# ADR-012: Process Supervision — Independent, Crash-Isolated Components

**Date:** 2026-06-30
**Author:** CServinL
**Status:** Accepted

## Context

Prisma currently runs as a single process (`prisma serve`). Every component —
REST API, WebSocket, UI static serving, the Graphify indexer, and the ChromaDB
vector index — lives inside that one process, sharing its memory, its threads,
and its fate.

Two incidents during PWA/WebSocket testing exposed the cost of this:

1. **ChromaDB partial-init crash.** `_ensure_client()` could leave a client
   handle set but its collection `None` after a transient failure. The
   background indexer thread then hit `None.upsert()` on the next file
   change — an unhandled exception that silently killed the `chroma-indexer`
   thread for the rest of the process's life. No error surfaced anywhere a
   user would see it; the only symptom was search results going stale forever.
2. **Graphify subprocess killed by inherited signal.** The extraction
   subprocess wasn't in its own process group, so a terminal Ctrl+C (SIGINT
   to the whole foreground process group) killed it directly and abruptly,
   independent of whatever cleanup logic ran in the parent. Every interrupted
   run left the index in "stale" with no clean recovery path short of another
   full run.

Both were fixed at the code level (see the `chroma_service.py` and
`graphify_service.py` commits on `feat/pwa-websocket`), but the fixes only
patch symptoms of a deeper structural issue: **there is no supervisor.**
Nothing in this system observes "a component died" and does something about
it. Recovering requires a human to notice broken behavior, find the log line,
and restart the entire process — losing every other component's state and
in-flight work along the way. And even that only works if the human knows to
do it; the ChromaDB failure produced no crash, no restart, just silent staleness.

There's also a second, unrelated problem this surfaces: Python caches
imported modules in memory for the life of a process. Editing `chroma_service.py`
on disk has zero effect on an already-running `prisma serve` until the whole
process restarts. The existing `/reload/*` endpoints (`/reload/vault`,
`/reload/indexer`, etc.) only construct fresh *instances* of already-imported
classes — they cannot pick up code changes. A full process restart is the
only way to load new code today, and a full process restart currently means
losing everything, not just the one component that changed.

## Decision

Split Prisma's runtime into a minimal **supervisor process** plus several
independently-restartable **worker processes**:

```
prisma serve
  └── supervisor (new, tiny entrypoint — no fastapi/chromadb/graphify imports)
       ├── spawns: API process       (uvicorn + prisma.server.app — REST + WS, no UI mount)
       ├── spawns: Web process       (uvicorn + a minimal static-file app — serves ui/build/ at /app)
       ├── spawns: Chroma server     (`chroma run` — ChromaDB's own server, not embedded)
       └── (on demand) Graphify subprocess — spawned by the API process's indexer, as today
```

### Supervisor

A new, deliberately dependency-free entrypoint. It imports nothing beyond the
Python standard library — no `fastapi`, no `chromadb`, no `pydantic`. This is
the "most basic and safe" layer the whole system is asked to keep running: if
every other dependency in this codebase has a bug, the supervisor should still
be able to report that fact and attempt a restart.

Responsibilities:
- Spawn each worker as a `subprocess.Popen`, in its own session
  (`start_new_session=True`, same fix applied to Graphify in this PR) so a
  terminal signal to the supervisor doesn't propagate directly to workers.
- Poll each worker's liveness (`proc.poll()`) on an interval.
- On unexpected exit, restart with exponential backoff (capped) to avoid a
  crash-looping component consuming resources or flooding logs.
- Expose a minimal control surface using `http.server` (not FastAPI) on a
  loopback-only port:
  - `GET /supervisor/status` — which workers are up, their PID, restart count
  - `POST /supervisor/restart/{name}` — deliberate restart of one worker
    (this is what actually reloads new code, unlike `/reload/*`)

### ChromaDB becomes a real server

Today `ChromaIndexer` embeds ChromaDB via `chromadb.PersistentClient(path=...)`
directly in the API process's background thread. That's why the partial-init
bug took down a thread inside the API process rather than being an isolated,
independently-recoverable failure.

Moving to `chroma run --path {vault}/chromadb --port {chroma_port}` as its own
supervised process, with the API process's `ChromaIndexer` using
`chromadb.HttpClient(host="127.0.0.1", port={chroma_port})` instead, means:
- A ChromaDB crash doesn't touch the API process's threads at all
- The supervisor can restart just the Chroma server without restarting the
  API, losing in-flight note edits, or dropping active WebSocket connections
- The persisted vector data's lifecycle is fully decoupled from the API
  process's lifecycle

The watchdog + incremental-embedding logic (`ChromaIndexer._loop`, the mtime
guard fixed in this PR) stays where it is, inside the API process — only the
storage backend moves out-of-process.

### API and Web as separate processes

Per discussion: the API (REST + WS) and the UI static file serving become
independent processes, each independently restartable. The API process no
longer mounts `/app`; a new minimal web-serving module (reusing the
`_CleanUrlStaticFiles` clean-URL resolution built in this PR) does that job
alone.

**Open question this creates:** browsers now see two different origins/ports
for one logical application — the API's port for `fetch()`/WebSocket calls,
the Web process's port for the page itself. This has real consequences:
- CORS must allow the Web process's origin to call the API
- The WebSocket connection (`new WebSocket(...)`) must point at the API's
  origin, not the page's own origin — `apiBase`-style configuration, already
  partially in place for Tauri, needs to also cover the browser/PWA case
- The PWA manifest's `scope`/`start_url` and the service worker's registration
  scope are tied to the origin the page loads from (the Web process), which
  is fine, but any same-origin assumptions elsewhere need auditing

For LAN/WAN deployments (ADR-011, deployment-models.md), a user-operated
reverse proxy in front of both processes — whatever the operator chooses to
run — can unify them into one public origin by routing `/app/*` to the Web
process and everything else to the API process. That reverse proxy is outside
Prisma's own scope; deployment-models.md documents it as operator-managed
infrastructure, not something the project depends on or ships. For local
dev/Tauri use, the client already supports an explicit, configurable
`apiBase`, so pointing it at a different port than the page's own origin is
not new. This ADR does not fully resolve the browser/PWA same-origin case for
LAN access without a proxy in front — that's a follow-up decision, not
blocking this ADR.

### Graphify stays request-scoped, not supervisor-managed

Graphify's subprocess is spawned on demand by the API process's
`GraphifyIndexer` (already fixed for graceful shutdown via `start_new_session`
+ `stop()` terminating it deliberately). It is not a long-running supervised
worker like the other three — it only exists for the duration of an indexing
run. No change from its current design beyond what's already shipped in this
PR.

### Relationship to existing `/reload/*` endpoints

The existing endpoints (`/reload/vault`, `/reload/zotero`, `/reload/indexer`,
`/reload/chroma`) remain — they're for lightweight, in-process state resets
(config changed, re-authenticate Zotero, etc.) that don't require new code.
`POST /supervisor/restart/{name}` is a different, heavier operation: a full
process restart that picks up code changes on disk. Both have a place; they
solve different problems.

## Alternatives Considered

### Status quo — single process, in-process reload only

Rejected. This is precisely what produced an undetectable silent failure
(ChromaDB) and an ungraceful, unrecoverable-without-full-restart failure
(Graphify). No amount of individual bug-fixing changes the fact that any
future bug in any component can still take down or silently wedge the whole
system, indefinitely, with no automated recovery.

### External process supervisor (systemd, supervisord)

Rejected for now. Standard, well-tested tooling, but: adds a deployment
dependency not available identically across the target platforms (Linux
systemd vs WSL2 vs eventual Windows-native support per the multi-platform
roadmap), and doesn't integrate with the existing `/reload/*` API-driven
control surface the UI's Settings panel already uses. A hand-rolled
supervisor keeps the control plane consistent (HTTP endpoints, one place to
look) and keeps deployment identical to today (`prisma serve`, nothing else
to install). Revisit if the hand-rolled version grows unwieldy.

### Keep ChromaDB embedded, isolate it into our own subprocess with custom IPC

Considered. Would still achieve crash isolation, but requires designing and
maintaining a bespoke IPC protocol for something ChromaDB already solves via
its own client/server mode. Using `chroma run` + `HttpClient` gets the same
isolation using the tool's own supported server mode — no custom protocol to
maintain.

## Consequences

### Positive
- A crash in ChromaDB, the API, or the Web server no longer takes down the
  other two, or the whole system
- The supervisor can detect and recover from failures automatically, without
  a human noticing broken behavior first
- `POST /supervisor/restart/{name}` gives an actual code-reload path, which
  `/reload/*` never could
- ChromaDB's data lifecycle is fully decoupled from the API process

### Negative
- More moving parts: 3 long-running processes instead of 1, plus the
  supervisor itself — more to reason about, more ports to manage
- ChromaDB calls go over loopback HTTP instead of an in-process call — small
  latency cost, acceptable given ChromaDB calls aren't on any hot path that's
  latency-sensitive at the scale this runs at
- Browser/PWA same-origin story needs a follow-up decision (an operator-run
  reverse proxy in front, or another unification strategy) for clean LAN
  access without a proxy
- Restart-storm handling (backoff, giving up after N attempts and surfacing
  a persistent failure rather than looping forever) needs to be right, or a
  broken component becomes a resource-burning loop instead of a silent one

## Related ADRs

- ADR-010: Transport Layer Strategy (the WebSocket broadcast mechanism this
  ADR's API process hosts)
- ADR-011: Authentication Strategy (zone-based auth; supervisor and Chroma
  server should bind loopback-only regardless of zone, only API/Web cross
  network boundaries)
