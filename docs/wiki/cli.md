# CLI Reference

All commands follow the pattern: `prisma [COMMAND] [SUBCOMMAND] [OPTIONS]`

Use `--config PATH` on `prisma review` and `prisma streams` commands to override the default config file (`~/.config/prisma/config.yaml`). Alternatively set the `PRISMA_CONFIG` environment variable.

---

## `prisma review`

Generate a one-shot literature review.

```bash
prisma review TOPIC [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output, -o PATH` | `./outputs/literature_review_<topic>.md` | Output file path |
| `--sources, -s TEXT` | config value | Comma-separated sources: `arxiv,semanticscholar,...` |
| `--limit, -l INT` | 10 | Max papers per source |
| `--zotero-only` | false | Search only your Zotero library (works offline) |
| `--include-authors` | false | Add author analysis to report |
| `--refresh-cache, -r` | false | Bypass cached metadata |
| `--config, -c PATH` | `~/.config/prisma/config.yaml` | Config file |

Examples:
```bash
prisma review "explainable AI" --output xai_review.md
prisma review "transformers" --sources arxiv,semanticscholar --limit 30
prisma review "federated learning" --include-authors
prisma review "mechanistic interpretability" --zotero-only   # works offline
```

---

## `prisma streams`

Manage persistent research streams.

### `prisma streams create`

```bash
prisma streams create NAME QUERY [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--description, -d TEXT` | — | Stream description |
| `--frequency, -f` | `weekly` | `daily`, `weekly`, `monthly`, `manual` |
| `--parent-collection, -p TEXT` | — | Parent Zotero collection key |
| `--config, -c PATH` | — | Config file |

### `prisma streams list`

```bash
prisma streams list [--status active|paused|archived]
```

### `prisma streams update`

```bash
prisma streams update [STREAM_ID] [--all] [--force] [--refresh-cache]
```

| Option | Description |
|--------|-------------|
| `--all, -a` | Update all active streams |
| `--force, -f` | Ignore frequency, update now |
| `--refresh-cache, -r` | Bypass cached metadata |

### `prisma streams info`

```bash
prisma streams info STREAM_ID
```

### `prisma streams summary`

```bash
prisma streams summary
```

---

## `prisma status`

Check system status.

```bash
prisma status [--verbose]
```

Checks: internet connectivity, config loaded, pending write queue, Zotero connectivity, dependencies, Ollama/LLM reachable.

---

## `prisma sync`

Flush the offline pending write queue to Zotero.

```bash
prisma sync
```

Prisma queues Zotero write actions (save paper, create collection) when offline or when Zotero is unavailable. Run this once connectivity is restored to push all queued actions. The queue is also flushed automatically on startup when online.

---

## `prisma zotero`

### `prisma zotero status`

Check Zotero integration: internet connectivity, Web API credentials, local HTTP server, desktop app, current mode.

```bash
prisma zotero status
```

### `prisma zotero duplicates`

Find and clean up duplicate items in your Zotero library.

```bash
prisma zotero duplicates [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--collection, -c TEXT` | Specific collection to clean |
| `--dry-run, -n` | Show what would be deleted without deleting |
| `--auto-select, -a` | Automatically keep oldest item |
| `--export-report, -e FILE` | Export analysis to JSON |
| `--verbose, -v` | Show detailed info per duplicate |

### `prisma zotero stats`

Show library statistics: item counts by type, items missing metadata, collection organization, recent additions.

```bash
prisma zotero stats [--collection TEXT]
```

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
