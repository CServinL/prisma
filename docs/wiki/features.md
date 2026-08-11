# Features

## Literature Review Pipeline

The core workflow: search → assess → deduplicate → analyze → report.

### 1. Multi-source Search

Prisma queries multiple academic databases one at a time, in source-quality order (highest first). Each is a quota-controlled, independent module (`prisma/integrations/sources/`) — a slow or rate-limited source never blocks the others from being tried. Each paper result is validated against academic criteria before being accepted.

Supported sources:
- **Semantic Scholar** — 214M+ papers, full metadata, abstracts
- **arXiv** — preprints with PDF links
- **PubMed** — biomedical/life-sciences literature, via NCBI E-utilities
- **OpenLibrary** — academic books via Internet Archive
- **Google Books** — book catalog with publisher metadata
- **IEEE Xplore** — engineering/CS papers (requires your own API key; real rate limit unverified as of 2026-07-29)
- **Zotero** — your personal library (deduplication and discovery)

### 2. Academic Validation

Every result is filtered through configurable criteria before entering the pipeline:

- Must have at least one author
- Must have a title (minimum 10 characters)
- Must have a venue, journal, or publisher
- Minimum abstract length (configurable, default 0)
- Publication year range (default: 1990–2030)
- Non-academic content excluded (blogs, news, social media)

Each result also receives a **confidence score** (0.0–1.0) computed from source quality, required fields, and academic indicators. Results below `min_confidence_score` (default 0.3) are discarded.

### 3. LLM Relevance Assessment

After search, each paper is passed to the local LLM (Ollama) for relevance assessment against the research topic. Papers scored as irrelevant are discarded before deep analysis. This filters out results that match keywords but are off-topic.

### 4. Duplicate Detection

Deduplication runs at two points:

**During stream ingestion** (`prisma.services.dedup.find_duplicate`) — each incoming paper is checked against the existing Zotero collection using a multi-level cascade:

| Level | Method | Speed |
|-------|--------|-------|
| 1 | DOI exact match | instant |
| 2 | Title exact match (normalized) | instant |
| 3 | Zotero `find_by_identifier` (network) | fast |
| 4 | NLTK stem overlap ≥ certain threshold | fast |
| 5 | NLTK stem overlap ≥ ambiguous threshold → LLM identity check | slow |

Before reaching the LLM (levels 4-5), a **stem pre-filter** discards papers with fewer than 2 stem roots in common with the stream query, reducing unnecessary LLM calls.

**Library maintenance** (`POST /maintenance/deduplicate`) — finds duplicate groups across the entire Zotero library. Defaults to `max_level=3` (DOI + title + year/author) for speed. Levels 4-5 are opt-in:

```bash
# Default: fast, no LLM
curl -X POST "http://localhost:8765/maintenance/deduplicate?dry_run=true"

# Thorough: includes NLTK + LLM
curl -X POST "http://localhost:8765/maintenance/deduplicate?dry_run=true&max_level=5"
```

The `sensitivity` query param (or `analysis.nltk_dedup_sensitivity` in config) controls NLTK thresholds for levels 4-5: `low | medium | high`.

### 5. Deep Analysis

The Analysis Agent uses the local LLM to generate structured summaries for each relevant, non-duplicate paper: key findings, methodology, contribution, and limitations.

### 6. Report Generation

The Report Agent synthesizes all summaries into a Markdown report with:
- Executive summary of the topic
- Individual paper summaries
- Thematic analysis: trends, conflicts, research gaps
- Research recommendations
- Optional author analysis (research directory: paper count, specialization keywords, key publications per author — no institutional affiliation, no search source captures it)
- Pipeline metadata (timing, source breakdown, paper counts)

Reports are saved to the configured output directory.

### 7. Auto-save to Zotero

When `auto_save_papers: true` is configured, papers that pass the confidence threshold (`min_confidence_for_save`, default 0.5) are saved to Zotero after analysis. Each saved item includes:
- Full metadata (title, authors, abstract, DOI, URL, journal, date)
- Tags: `Prisma-Discovery`, `Confidence-X.XX`, `Source-<name>`, `Topic-<topic>`
- Prisma summary appended to the abstract note

---

## Research Streams

A Research Stream is a persistent, named research topic that continuously monitors for new papers. See [Research Streams](streams.md).

---

## Vault

The vault is a local Markdown-file knowledge base, organized into typed folders:

| Folder | Type | Purpose |
|--------|------|---------|
| `notes/` | note | Free-form research notes |
| `sources/` | source | Imported papers and references |
| `chats/` | chat | Saved AI conversations |
| `streams/` | stream | Research stream output |

All vault operations go through the REST API (`GET /notes`, `PUT /notes/{slug}`, etc.). Wiki-links between notes (`[[slug]]`) are resolved at render time.

---

## Chat

The chat assistant (see `ADR-014-chat-llm-backend-interface.md`) has retrieval access to the whole vault — notes, sources, and **past chat transcripts**, not just the current conversation — via `search_vault` (ChromaDB semantic search) and `graph_context` (knowledge graph traversal), both called on demand as the model needs them. Claims it makes are self-reported with per-claim attribution back to the source vault item (see `docs/concepts/claim.md` / ADR-017 / ADR-019).

### Chat as a session graph

A chat isn't a flat message list — it's its own graph (ADR-019, see `docs/concepts/chat-session-graph.md` for the full node/edge taxonomy). The **main line** is the plain `User <-> AI` turn sequence (`TurnNode`, in order); everything else a turn produces branches off it rather than competing for a position in that sequence:

- **Tool calls** (`ToolCallNode`) — which tool, what args, and (unlike the pre-ADR-019 model) the actual result, persisted, so it can be recalled later instead of only ever re-run.
- **Claims** (`CitedClaimNode`/`InferenceNode`) — per-claim attribution, see "Claims" above.
- **Regeneration attempts** (`alternates`) — prior replies to the same turn, preserved when regenerated, each keeping its own model.
- **Reasoning steps** (`ThinkingNode`) — schema ships, nothing populates it yet (gated behind a still-deferred model-category flag).

A `SessionOrchestrator` assembles context per turn: a cheap default (system prompt + Excerpt + a token-bounded walk of the main line — the same algorithm the pre-graph model used, just relocated) plus a fourth tool, `recall`, that searches the *whole* session graph — including turns the rolling window has already dropped — when the model decides it's missing something. `RECALL` also reaches into a bounded set of *other* chats' session graphs (the most recently active few, at a discounted relevance weight, capped to keep cost bounded regardless of vault size) — see `docs/concepts/chat-session-graph.md`'s Status section for the exact mechanics.

### Chat instructions

Settings → **Chat instructions** is a standing, user-edited system prompt — CLAUDE.md-style: preferences and rules that apply to every chat, every turn ("always answer in Spanish," tone, things to always/never do), not one-off requests (those belong in the chat itself). Manual only — the assistant never writes to it. Backed by `GET`/`PUT /chat/system-prompt`, which persists to `~/.config/prisma/chat_system_prompt.md` and applies immediately (no restart).

---

## Search

### Regular Search

`GET /search?q=...` — keyword search over all vault notes. An in-memory index (keyed by file mtime) is refreshed on every request: only files whose mtime changed are re-read from disk. Scoring:

- Each matching term: +1.0
- Term found in title: +4.0 bonus
- All terms present (AND match): +3.0 bonus
- NLTK stem overlap with query: +0.5 per shared stem root (e.g. "learning" matches "learned", "learns")

Returns up to 30 results ordered by score, with an excerpt from the first matching line.

### Deep Search (Semantic)

`GET /search/deep?q=...` — two-stage semantic search:

1. **ChromaDB** embeds the query via `nomic-embed-text` and retrieves the top 60 matching chunks across all indexed files. Chunk-level distances are aggregated to file-level scores (best chunk wins).
2. **Knowledge graph re-ranking** applies a title-match boost using knowledge graph node titles, then returns the top 20 results with matched concepts.
3. **NLTK re-rank boost**: after semantic scoring, each result receives a +0.05 bonus per shared stem root between its title/body and the query. This adjusts ordering without overriding semantic scores.

Deep search is slower than regular search but finds semantically related content even without exact keyword overlap.

---

## Knowledge Graph

A background indexer (`KnowledgeGraphService`, native — replaced the third-party `graphify` pip dependency, see ADR-012's follow-up section and `TODO.md`) watches the vault root and extracts a knowledge graph via a local Ollama model, chunked **per section** (not per-file) so no single oversized document can exceed the model's token budget. The graph is persisted to an embedded Kùzu database at `{vault_root}/kg-out/`. On query, it returns related concepts and connections relevant to the search query.

Status is exposed at `GET /status` under `knowledge_graph` and shown in the desktop app status popover.

---

## ChromaDB Semantic Index

A background indexer maintains a persistent ChromaDB collection at `{vault_root}/chromadb/`. It watches the vault for file changes and embeds modified `.md` files in chunks using the configured `nomic-embed-text` model via Ollama. The manifest tracks per-file mtimes so only changed files are re-embedded on restart.

At startup, if the embedding model is not available in Ollama, the indexer logs one actionable error (with the `ollama pull` command) and skips indexing — no per-file errors. See [Installation](installation.md) for required models.

Status (chunk count, files indexed, model name) is exposed at `GET /status` under `chroma` and shown in the desktop app.

---

## Offline Mode

Prisma detects network connectivity at startup and adapts:

- **Online**: full pipeline available; Zotero reads and writes go through the Web API
- **Offline**: literature review and research stream updates are both disabled (both need internet — source search APIs, and Zotero's Web API for reads too, since there is no local Zotero access path anymore); creating a *new* stream still works, with its Zotero collection creation queued and flushed automatically on next online startup

---

## What is NOT implemented yet

- IEEE Xplore's real rate limit/daily quota — IEEE publishes none of this publicly; the current default is a conservative guess, unverified against a real API key as of 2026-07-29
