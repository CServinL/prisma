# Configuration

Prisma loads configuration from `~/.config/prisma/config.toml` by default. Override with `--config PATH` or the `PRISMA_CONFIG` environment variable.

Start from the example:
```bash
cp /path/to/repo/config.example.toml ~/.config/prisma/config.toml
```

---

## Full Reference

```toml
# ── Vault ─────────────────────────────────────────────────────────────────────
vault_root = "~/prisma-vault"          # empty/omitted = ~/prisma-vault

# ── Zotero ──────────────────────────────────────────────────────────────────
[sources.zotero]
enabled = true

# Reads and writes: Zotero Web API only (no local Zotero Desktop
# integration — see ADR-008's follow-up)
api_key = ""                           # from zotero.org/settings/keys
# api_key_env = "ZOTERO_API_KEY"       # or: env var holding it instead — takes priority over api_key, keeps the real key out of this file
library_id = ""                        # your numeric user ID
# library_id_env = "ZOTERO_LIBRARY_ID" # or: env var holding it instead — takes priority over library_id
library_type = "user"                  # "user" | "group"

# Search behavior
default_collections = []              # empty = search all collections
include_notes = false
include_attachments = false

# ── Search ───────────────────────────────────────────────────────────────────
[search]
default_limit = 10

# Sources in priority order (sorted by quality automatically when prefer_high_quality = true)
sources = [
    "semanticscholar",                # ⭐⭐⭐⭐⭐
    "arxiv",                          # ⭐⭐⭐⭐⭐
    "openlibrary",                    # ⭐⭐⭐⭐
    "googlebooks",                    # ⭐⭐⭐⭐
    "zotero",                         # ⭐⭐⭐ (dedup/discovery)
]

prefer_high_quality = true             # search 5-star sources first
min_confidence_score = 0.3             # discard results below this
require_academic_validation = true     # apply academic content filters

# ── LLM ─────────────────────────────────────────────────────────────────────
[llm]
provider = "ollama"
model = "qwen2.5:7b-32k"
host = "localhost:11434"               # WSL: use Windows host IP

# ── Chat (ADR-014: backend-agnostic — ollama today, openrouter/anthropic-capable) ──
[chat]
provider = "ollama"                    # ollama | openrouter | anthropic
model = "qwen2.5:7b-32k"
pool = "local-ollama"                  # must match a compute_pools entry below
context_window = 32768                 # this backend's real usable context (verify via /api/ps, not a claimed value)
max_tokens = 2000                      # hard cap on generated tokens per completion
# base_url = ""                        # override the provider's default; omit to derive from provider
# api_key_env = ""                     # env var holding the API key (omit for local Ollama)

# ── Compute pools (GPU/inference lease arbitration — ADR-012) ────────────────
# Each [[compute_pools.models]] entry is always a table (TOML arrays must be
# homogeneous — no bare-string shorthand); only `name` is required.
#
# [[compute_pools]]
# name = "local-ollama"          # single GPU — N concurrent calls to the SAME model
# max_concurrent = 3             # model_affinity omitted — defaults to true
#
# [[compute_pools]]
# name = "cloud_api"
# max_concurrent = 4             # rate-limited cloud inference endpoint
# model_affinity = false         # auto-scaled/auto-routed — no reload penalty to model

# ── Output ───────────────────────────────────────────────────────────────────
[output]
directory = "./outputs"
format = "markdown"

# ── Analysis ─────────────────────────────────────────────────────────────────
[analysis]
summary_length = "medium"             # "short" | "medium" | "long"
nltk_dedup_sensitivity = "medium"     # "low" | "medium" | "high"
                                       # Controls NLTK stem-overlap thresholds at dedup levels 4-5.
                                       # low: certain=13 ambiguous=10
                                       # medium: certain=10 ambiguous=7  (default)
                                       # high:   certain=7  ambiguous=5

# ── Retrieval (ChromaDB semantic search) ─────────────────────────────────────
[retrieval]
embedding_model = "nomic-embed-text"  # Ollama model used for vault embeddings
ollama_base_url = "http://localhost:11434"  # WSL: use Windows host IP

# ── Knowledge graph — native KnowledgeGraphService (Kùzu-backed) ─────────────
[kg]
index_extensions = [".md", ".txt"]   # file types included in the graph index (with or without leading dot, both work)
token_budget = 1000                  # per-section chunk size sent to the LLM (smaller = better extraction quality, see docs/kg-extraction-context-length.md)
extraction_concurrency = 3           # max concurrent extraction calls (cross-file + within-file combined)
max_entities = 15                    # max entities extracted per chunk — a cloud-routed model can afford a much higher cap than a local one
max_relationships = 20               # max relationships extracted per chunk
max_output_fraction = 0.25           # fraction of the model's context window reserved for output tokens
```

---

## Common Presets

### High-quality papers only
```toml
[search]
sources = ["semanticscholar", "arxiv"]
min_confidence_score = 0.5
```

### Include books
```toml
[search]
sources = ["semanticscholar", "arxiv", "openlibrary", "googlebooks"]
```

### Zotero-only search
```toml
[search]
sources = ["zotero"]
```

### WSL + Windows Ollama
```toml
[llm]
host = "172.x.x.x:11434"   # get with: ip route show | grep default | awk '{print $3}'

[retrieval]
ollama_base_url = "http://172.x.x.x:11434"  # same Windows host IP, for ChromaDB embeddings
```
