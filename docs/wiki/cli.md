# CLI Reference

The CLI is deliberately minimal — it only covers what can't be an HTTP call
(starting the server, checking readiness before/without one running, and
bootstrapping auth). Everything else — literature review, research streams,
Zotero library management — is API-only. See "Moved to the API" below for
the exact routes.

All commands follow the pattern: `prisma [COMMAND] [SUBCOMMAND] [OPTIONS]`

---

## `prisma serve`

Start Prisma: a supervisor process managing the API, Web, ChromaDB, and
knowledge graph server processes independently (see ADR-012). A crash in
any one of them no longer takes down the others.

```bash
prisma serve [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | 8765 | API port |
| `--web-port` | 8766 | Web (UI) port |
| `--chroma-port` | 8767 | ChromaDB server port |
| `--kg-port` | 8768 | Knowledge graph server port |
| `--supervisor-port` | 8760 | Supervisor control port (loopback only) |
| `--reload` | false | Auto-reload the API on code changes (dev only) |

---

## `prisma status`

Check system status and readiness — the one diagnostic that has to run
outside the API, since it checks whether the config file, dependencies, and
network are even in a state where `prisma serve` would succeed.

```bash
prisma status [--verbose]
```

Checks: internet connectivity, config loaded, pending write queue, Zotero
Web API credentials + reachability, dependencies, Ollama/LLM reachable.

---

## `prisma reload-resources`

Re-read `compute_pools` from `config.yaml` into an already-running
supervisor — no restart, no lost in-flight leases. A thin convenience
wrapper over the supervisor's own `POST /supervisor/resources/reload`.

```bash
prisma reload-resources [--supervisor-port PORT]
```

---

## `prisma auth`

### `prisma auth hash-password`

Prompts for a password (hidden, confirmed twice) and prints its bcrypt
hash. Paste the output into `~/.config/prisma/config.yaml` under
`server.auth.password_hash`, and set `server.auth.mode: password` (ADR-011).
This can't be an API call — the server has no password configured yet when
you run it, and you wouldn't want to send a plaintext password over the
network just to get its hash locally.

```bash
prisma auth hash-password
```

---

## Moved to the API (2026-07-27)

`prisma review`, `prisma streams`, and `prisma zotero` were removed — each
had a full HTTP equivalent already, or gained one as part of this change.
Use the API directly (curl, the UI, or your own script):

| Old CLI command | API route |
|---|---|
| `prisma review TOPIC` | `POST /review` (poll `GET /review/{job_id}`) |
| `prisma streams create` | `POST /streams` |
| `prisma streams list` | `GET /streams` |
| `prisma streams info SLUG` | `GET /streams/{slug}` |
| `prisma streams update SLUG [--force]` | `POST /streams/{slug}/run?force=` |
| `prisma streams update --all` | loop `POST /streams/{slug}/run` over `GET /streams` |
| `prisma streams summary` | compute client-side from `GET /streams` |
| `prisma zotero status` | `GET /zotero/status` |
| `prisma zotero duplicates` | `POST /maintenance/deduplicate` (poll `GET /maintenance/deduplicate/{job_id}`) |
| `prisma zotero stats` | `GET /zotero/stats` (new route) |
| `prisma sync` | `POST /zotero/sync-pending` (new route) |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PRISMA_CONFIG` | Override default config file path |
| `OLLAMA_HOST` | Override LLM host (e.g. `172.x.x.x:11434`) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Configuration error |
| `3` | Zotero connection error |
| `4` | LLM integration error |
