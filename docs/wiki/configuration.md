# Configuration

Prisma loads configuration from `~/.config/prisma/config.yaml` by default. Override with `--config PATH` or `PRISMA_CONFIG_PATH`.

Start from the example:
```bash
cp /path/to/repo/config.example.yaml ~/.config/prisma/config.yaml
```

---

## Full Reference

```yaml
# ── Zotero ──────────────────────────────────────────────────────────────────
sources:
  zotero:
    enabled: true
    mode: "hybrid"                        # "hybrid" | "local_api"

    # Reads: Zotero Desktop local HTTP (Windows host IP from WSL)
    local_server_url: "http://172.x.x.x:23119"
    local_server_timeout: 5

    # Writes: Zotero Web API
    api_key: ""                           # from zotero.org/settings/keys
    library_id: ""                        # your numeric user ID
    library_type: "user"                  # "user" | "group"
    prefer_web_api_when_online: true
    disable_writes_when_offline: true
    auto_detect_network: true
    network_timeout: 5

    # Search behavior
    default_collections: []              # empty = search all collections
    include_notes: false
    include_attachments: false

    # Auto-save discovered papers to Zotero
    auto_save_papers: true
    auto_save_collection: "Prisma Discoveries"
    min_confidence_for_save: 0.5         # 0.0–1.0

# ── Search ───────────────────────────────────────────────────────────────────
search:
  default_limit: 10

  # Sources in priority order (sorted by quality automatically when prefer_high_quality: true)
  sources:
    - semanticscholar                    # ⭐⭐⭐⭐⭐
    - arxiv                              # ⭐⭐⭐⭐⭐
    - openlibrary                        # ⭐⭐⭐⭐
    - googlebooks                        # ⭐⭐⭐⭐
    - zotero                             # ⭐⭐⭐ (dedup/discovery)

  prefer_high_quality: true             # search 5-star sources first
  min_confidence_score: 0.3             # discard results below this

  validation:
    require_authors: true
    require_title: true
    require_venue_or_publisher: true
    min_authors: 1
    min_title_length: 10
    min_abstract_length: 0
    require_publication_date: false
    min_publication_year: 1990
    max_publication_year: 2030
    exclude_non_academic: true

# ── LLM ─────────────────────────────────────────────────────────────────────
llm:
  provider: "ollama"
  model: "llama3.1:8b"
  host: "localhost:11434"               # WSL: use Windows host IP

# ── Output ───────────────────────────────────────────────────────────────────
output:
  directory: "./outputs"
  format: "markdown"

# ── Analysis ─────────────────────────────────────────────────────────────────
analysis:
  summary_length: "medium"             # "short" | "medium" | "long"
```

---

## Common Presets

### High-quality papers only
```yaml
search:
  sources: [semanticscholar, arxiv]
  min_confidence_score: 0.5
  validation:
    min_abstract_length: 100
    min_publication_year: 2015
```

### Include books
```yaml
search:
  sources: [semanticscholar, arxiv, openlibrary, googlebooks]
```

### Offline / Zotero-only
```yaml
search:
  sources: [zotero]
sources:
  zotero:
    mode: "local_api"
    local_server_url: "http://172.x.x.x:23119"
```

### WSL + Windows Ollama
```yaml
llm:
  host: "172.x.x.x:11434"   # get with: ip route show | grep default | awk '{print $3}'
```
