# Configuration

Prisma loads configuration from `~/.config/prisma/config.yaml` by default. Override with `--config PATH` or the `PRISMA_CONFIG` environment variable.

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
    server_url: "http://172.x.x.x:23119"
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
  model: "qwen2.5:7b-32k"
  host: "localhost:11434"               # WSL: use Windows host IP

# ── Chat (ADR-014: backend-agnostic — ollama today, openrouter/anthropic-capable) ──
chat:
  provider: "ollama"                    # ollama | openrouter | anthropic
  model: "qwen2.5:7b-32k"
  pool: "local-ollama"                  # must match a compute_pools entry below
  context_window: 32768                 # this backend's real usable context (verify via /api/ps, not a claimed value)
  max_tokens: 2000                      # hard cap on generated tokens per completion
  # base_url: null                      # override the provider's default; omit to derive from provider
  # api_key_env: null                   # env var holding the API key (omit for local Ollama)

# ── Compute pools (GPU/inference lease arbitration — ADR-012) ────────────────
# compute_pools:
#   - name: local-ollama          # single GPU — N concurrent calls to the SAME model
#     max_concurrent: 3           # model_affinity omitted — defaults to true
#   - name: cloud_api
#     max_concurrent: 4           # rate-limited cloud inference endpoint
#     model_affinity: false       # auto-scaled/auto-routed — no reload penalty to model

# ── Output ───────────────────────────────────────────────────────────────────
output:
  directory: "./outputs"
  format: "markdown"

# ── Analysis ─────────────────────────────────────────────────────────────────
analysis:
  summary_length: "medium"             # "short" | "medium" | "long"
  nltk_dedup_sensitivity: "medium"     # "low" | "medium" | "high"
                                       # Controls NLTK stem-overlap thresholds at dedup levels 4-5.
                                       # low: certain=13 ambiguous=10
                                       # medium: certain=10 ambiguous=7  (default)
                                       # high:   certain=7  ambiguous=5

# ── Retrieval (ChromaDB semantic search) ─────────────────────────────────────
retrieval:
  embedding_model: "nomic-embed-text"  # Ollama model used for vault embeddings
  ollama_base_url: "http://localhost:11434"  # WSL: use Windows host IP

# ── Knowledge graph — native KnowledgeGraphService (Kùzu-backed) ─────────────
kg:
  index_extensions: [".md", ".txt"]   # file types included in the graph index
  token_budget: 1000                  # per-section chunk size sent to the LLM (smaller = better extraction quality, see docs/kg-extraction-context-length.md)
  extraction_concurrency: 3           # max concurrent extraction calls (cross-file + within-file combined)
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
    server_url: "http://172.x.x.x:23119"
```

### WSL + Windows Ollama
```yaml
llm:
  host: "172.x.x.x:11434"   # get with: ip route show | grep default | awk '{print $3}'

retrieval:
  ollama_base_url: "http://172.x.x.x:11434"  # same Windows host IP, for ChromaDB embeddings
```
