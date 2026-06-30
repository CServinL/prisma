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
.venv/bin/prisma serve        # API on :8765, UI at :8765/app
```

Build the UI first if not already built:
```bash
cd ui && npm install && npm run build
```

## Before opening a PR

Regenerate the architecture diagram whenever Python modules are added, removed, or renamed:

```bash
.venv/bin/python docs/reflection/module-map.py
```

Include the updated `docs/reflection/module-map.html` in the PR so reviewers can inspect the diagram.
