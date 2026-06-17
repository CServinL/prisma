# Features

## Literature Review Pipeline

The core workflow: search → assess → deduplicate → analyze → report.

### 1. Multi-source Search

Prisma queries multiple academic databases in parallel, sorted by source quality (highest first). Each result is validated against academic criteria before being accepted.

Supported sources:
- **Semantic Scholar** — 214M+ papers, full metadata, abstracts
- **arXiv** — preprints with PDF links
- **OpenLibrary** — academic books via Internet Archive
- **Google Books** — book catalog with publisher metadata
- **Zotero** — your personal library (deduplication and discovery)
- **Academia.edu** — framework exists, HTML parsing not yet implemented

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

Before analysis, Prisma checks whether each paper already exists in your Zotero library by searching by title. Existing papers are skipped (counted as `papers_existing` in output metadata).

Within a single search run, duplicates across sources are removed by normalized title comparison.

### 5. Deep Analysis

The Analysis Agent uses the local LLM to generate structured summaries for each relevant, non-duplicate paper: key findings, methodology, contribution, and limitations.

### 6. Report Generation

The Report Agent synthesizes all summaries into a Markdown report with:
- Executive summary of the topic
- Individual paper summaries
- Thematic analysis: trends, conflicts, research gaps
- Research recommendations
- Optional author analysis (key researchers, affiliation)
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

## Search

### Regular Search

`GET /search?q=...` — keyword search over all vault notes. An in-memory index (keyed by file mtime) is refreshed on every request: only files whose mtime changed are re-read from disk. Scoring:

- Each matching term: +1.0
- Term found in title: +4.0 bonus
- All terms present (AND match): +3.0 bonus

Returns up to 30 results ordered by score, with an excerpt from the first matching line.

### Deep Search (Semantic)

`GET /search/deep?q=...` — two-stage semantic search:

1. **ChromaDB** embeds the query via `nomic-embed-text` and retrieves the top 60 matching chunks across all indexed files. Chunk-level distances are aggregated to file-level scores (best chunk wins).
2. **Graphify re-ranking** applies a title-match boost using knowledge graph node titles, then returns the top 20 results with matched concepts.

Deep search is slower than regular search but finds semantically related content even without exact keyword overlap.

---

## Knowledge Graph (Graphify)

A background indexer watches the vault root and extracts a knowledge graph via a local Ollama model. The graph is persisted to `{vault_root}/graphify-out/`. On query, Graphify returns related concepts and connections relevant to the search query.

Status is exposed at `GET /status` under `graphify` and shown in the desktop app status popover.

---

## ChromaDB Semantic Index

A background indexer maintains a persistent ChromaDB collection at `{vault_root}/chromadb/`. It watches the vault for file changes and embeds modified `.md` files in chunks using the configured `nomic-embed-text` model via Ollama. The manifest tracks per-file mtimes so only changed files are re-embedded on restart.

At startup, if the embedding model is not available in Ollama, the indexer logs one actionable error (with the `ollama pull` command) and skips indexing — no per-file errors. See [Installation](installation.md) for required models.

Status (chunk count, files indexed, model name) is exposed at `GET /status` under `chroma` and shown in the desktop app.

---

## Offline Mode

Prisma detects network connectivity at startup and adapts:

- **Online**: full pipeline available; Zotero writes go to the Web API
- **Offline**: literature review is disabled (requires internet for APIs); research stream reads work via Zotero local HTTP; writes are queued to a local pending queue and flushed automatically on next online startup

---

## What is NOT implemented yet

- Academia.edu result parsing (the HTTP request is made but HTML parsing is absent)
- PubMed source (referenced in docs but absent from `SearchAgent`)
- ResearchGate source (referenced in docs, absent from code)
