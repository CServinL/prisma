# prisma

FastAPI research assistant server + SvelteKit UI.

Read before writing code:
- `docs/ontologia.md` — entity map, domain axioms
- `docs/wiki/architecture.md` — package layout, service threads, client matrix

## Key conventions

- Pydantic v2 for all structured data — never `@dataclass`
- All API responses are typed Pydantic models
- Vault stored as flat Markdown files — no database
- Zotero is the bookmark layer (stream runs write here); vault is the second brain (deliberate import only via `POST /zotero/import/{key}`)

## Running locally

```bash
.venv/bin/prisma serve        # supervisor: API :8765, Web/UI :8766, ChromaDB :8767 (see ADR-012)
```

**Never `git checkout`/switch branches in this repo while `prisma serve` is running from it.**
The editable install reads code from the working tree on disk, not a fixed commit — switching
branches mid-session silently changes what code runs on the *next* restart, with no warning.
If you need to merge a PR or rebase another branch, either wait until the user confirms the
server is stopped, or do the git work in a separate worktree.

## Building the UI

Build the UI first if not already built:
```bash
cd ui && npm install && npm run build
```

## Before opening a PR

Regenerate all diagrams before opening a PR:

```bash
bash docs/diagrams/gen.sh
```

Diagrams live in `docs/diagrams/`. Include updated HTML files in the PR — reviewing them is part of the PR checklist:

| File | Type | What it shows |
|------|------|---------------|
| `01_system_overview.html` | SystemMap | Clients → API → services → storage → external |
| `02a_zotero_classes.html` | ClassMap | Zotero client hierarchy and interfaces |
| `02b_zotero_state.html` | StateMap | Online / degraded / offline connection states |
| `03_stream_update_flow.html` | SequenceMap | Stream refresh: API → agents → Zotero |
| `04_vault_data_model.html` | ERMap | Vault logical data model |
| `05_transport_auth.html` | SystemMap | REST vs WebSocket transport + auth zones (local/LAN/WAN) |
| `06_process_supervision.html` | SystemMap | Supervisor topology + crash/restart recovery paths |
| `07a_compute_pool_topology.html` | SystemMap | GPU/LLM compute-pool: the three Ollama callers, the arbiter, the shared backend |
| `07b_compute_pool_contention.html` | SequenceMap | What happens when two callers want different models at once (409 → backoff retry → grant) |
