# CLI Reference

All commands follow the pattern: `prisma [COMMAND] [SUBCOMMAND] [OPTIONS]`

Global option available on all commands: `--config PATH` to override the default config file.

---

## `prisma review`

Generate a one-shot literature review.

```bash
prisma review TOPIC [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output, -o PATH` | stdout | Output file path |
| `--sources, -s TEXT` | config value | Comma-separated sources: `arxiv,semanticscholar,...` |
| `--limit, -l INT` | 10 | Max papers per source |
| `--zotero-only` | false | Search only your Zotero library |
| `--include-authors` | false | Add author analysis to report |
| `--refresh-cache, -r` | false | Bypass cached metadata |
| `--config, -c PATH` | `~/.config/prisma/config.yaml` | Config file |

Examples:
```bash
prisma review "explainable AI" --output xai_review.md
prisma review "transformers" --sources arxiv,semanticscholar --limit 30
prisma review "federated learning" --include-authors
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

Checks: config loaded, Zotero connectivity, storage available, Ollama/LLM reachable.

---

## `prisma zotero`

### `prisma zotero test-connection`

Tests both local HTTP and Web API connections and reports which are available.

### `prisma zotero list-collections`

Lists all collections in your Zotero library.

### `prisma zotero sync-status`

Shows pending offline write queue status and flushes if online.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PRISMA_CONFIG_PATH` | Override default config path |
| `PRISMA_DEBUG` | Set to `1` for debug output |
| `ZOTERO_API_KEY` | Override config API key |
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
