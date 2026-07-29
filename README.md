<p align="center">
  <img src="ui/static/prisma-icon.svg" alt="Prisma" width="120">
</p>

# Prisma
*Research workspace with semantic search over your papers and notes — Zotero-integrated, local-first, and reachable from a browser or desktop app.*

[![Sponsor](https://img.shields.io/badge/Sponsor-CServinL-ea4aaa?logo=github)](https://github.com/sponsors/CServinL)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

## Overview

**Prisma** is a Research Library Assistant that helps researchers intelligently organize, curate, and enhance their research libraries using **Zotero as the primary organization tool**. It discovers research content, assesses relevance, and provides intelligent library management.

**Architecture:** `prisma serve` runs a small supervisor that isolates the API, Web UI, ChromaDB, and native knowledge-graph module into independent, crash-recoverable processes — a flat-Markdown vault (notes, sources, chats, streams) is the shared workspace, with a CLI, REST/WebSocket API, and installable PWA/desktop UI all operating on it.

## System Requirements

**Required:**
- **Ollama** (or another configured LLM provider — OpenRouter, llama.cpp) for research analysis, chat, and knowledge-graph extraction

**Optional:**
- **Zotero Web API** access (for library integration — discovering, deduplicating, and saving research; Prisma runs without it, just without the bookmark layer)
- **Internet** access to source APIs (arXiv, Semantic Scholar, etc.) and the Zotero Web API

## Key Features

- **🌐 Multi-Source Discovery**: Searches papers (arXiv, Semantic Scholar, PubMed, IEEE Xplore\*) and books (OpenLibrary, Google Books) per stream query, each source independently quota-controlled (\*IEEE Xplore requires your own API key)
- **🔗 Zotero Bookmarking**: Saves discovered papers into your existing Zotero library via its Web API — Zotero stays the library, Prisma adds to it
- **🌊 Research Streams**: Persistent topic monitoring — scheduled searches automatically discover, deduplicate, and file new papers into a dedicated Zotero collection per stream
- **⭐ Quality-Rated Sources**: Each search source is rated 1-5 stars by API reliability/structure, prioritizing curated academic APIs over scraping-dependent ones
- **🛡️ Academic Validation**: Filters out non-academic content (blogs, ads, spam) via keyword/structure heuristics plus LLM confidence scoring
- **📖 Abstract-Level Relevance**: LLM assessment runs on title + abstract, not full PDF text — importing a paper into your vault separately converts its PDF to readable Markdown
- **🤖 AI-Powered Curation**: Local or cloud-capable LLMs (Ollama, OpenRouter, llama.cpp) assess relevance, score confidence, and summarize what's found
- **🏷️ Smart Tagging (Streams only)**: Papers saved via a Research Stream are auto-tagged with confidence score, source, topic, and stream ID
- **🗂️ Vault Workspace**: A local, flat-Markdown second brain for notes, sources, and chats — `prisma serve` opens it as a web app, installable PWA, or native desktop shell
- **💬 Chat**: Ask Prisma questions about your vault — grounded in ChromaDB semantic search + native knowledge-graph context, with tool-calling, citations, and a pinning/Excerpt model for managing context budget across local or cloud-capable LLM backends
- **🕸️ Native Knowledge Graph**: Entity/relationship extraction (structured LLM output, no third-party dependency) stored in an embedded graph DB, re-ranking search results and answering "what connects to what" — with a live progress UI (sync status, extraction stats, failure inspection)
- **🔍 Semantic Search**: ChromaDB embeddings + the knowledge graph re-rank results beyond keyword matching
- **🧹 Deduplication**: Multi-level matching (DOI, exact title, year+author, NLTK stem overlap, LLM identity check) catches duplicates other tools miss, on demand or during stream refresh
- **🔄 Vault Sync**: Server-orchestrated sync keeps the [desktop app](https://github.com/CServinL/prisma-desktop) and server vault in agreement, working offline and reconciling on reconnect
- **⚡ Live Updates**: Vault changes and stream-refresh progress push to the UI over WebSocket in real time

## Research Library Management Process

**Prisma's research library management workflow:**

1. **Discover Research** - Query external APIs and Zotero libraries using stream's search criteria
   - **External Sources**: arXiv, Semantic Scholar, PubMed, etc.
   - **Zotero Libraries**: Existing research collections and newly imported items
2. **Assess Relevance** - Use LLM to quickly evaluate research relevance to the topic
3. **Curate Content** - Filter and organize relevant research immediately
4. **For Relevant Research:**
   - **Check Zotero Storage** - Search the Zotero Web API for duplicates
   - **Save to Zotero** - Store new research and add to stream collection (if Zotero is reachable)
   - **Mark Unsaved** - Flag research that couldn't be saved (if Zotero is unreachable or not configured)
5. **Analyze Content** - Comprehensive LLM analysis for research assessment
6. **Enhance Library** - Improve organization and provide research insights (noting any unsaved research)

**Note**: Zotero serves dual roles as both a **source integration** (for discovering existing relevant research) and **primary organization tool** (for organizing and managing research collections).

## CLI Commands

The CLI is deliberately minimal — it only covers what can't be an HTTP call
(start the server, check readiness, bootstrap auth). Research streams,
literature review, and Zotero library management are API-only.

> 📖 **Complete CLI Reference**: See [CLI Documentation](docs/wiki/cli.md) for detailed command options, examples, and the full command→API-route mapping.

```bash
# Start the server
prisma serve

# Check system status
prisma status --verbose
```

### Research Streams, Review, and Zotero (via the API)
```bash
# Create a research stream
curl -X POST http://127.0.0.1:8765/streams \
  -H 'Content-Type: application/json' \
  -d '{"title": "Stream Name", "query": "search query", "refresh_frequency": "weekly"}'

# Generate a literature review
curl -X POST http://127.0.0.1:8765/review \
  -H 'Content-Type: application/json' \
  -d '{"topic": "neural networks"}'

# Zotero status
curl http://127.0.0.1:8765/zotero/status
```

## Quick Start

### Regular users (install from PyPI)

```bash
pip install prisma
prisma serve
```

### Run the workspace UI

```bash
prisma serve
```

Opens the vault workspace at `http://127.0.0.1:8766/app` — installable as a PWA, or wrapped in the [Tauri desktop shell](https://github.com/CServinL/prisma-desktop). See [Installation](docs/wiki/installation.md) for the full setup.

### Developers (install from source, editable)

```bash
git clone https://github.com/CServinL/prisma.git
cd prisma
python3 -m venv ~/prisma
source ~/prisma/bin/activate
pip install -e ".[dev]"
prisma --help
```

Changes to source files are immediately active — no reinstall needed.

## Documentation

**[📖 Wiki](docs/wiki/README.md)** — complete documentation

- [Features](docs/wiki/features.md) — what Prisma does and how
- [Installation](docs/wiki/installation.md) — user and developer setup
- [CLI Reference](docs/wiki/cli.md) — all commands and options
- [Configuration](docs/wiki/configuration.md) — YAML reference
- [Research Streams](docs/wiki/streams.md) — persistent topic monitoring
- [Sources](docs/wiki/sources.md) — quality ratings and academic validation
- [Zotero Integration](docs/wiki/zotero.md) — Web API client, connectivity/reachability, offline write queue
- [Architecture](docs/wiki/architecture.md) — components and data flow
- [Roadmap](docs/wiki/roadmap.md) — planned features

## Technology Stack

- **🐍 Python 3.12+** — pip/setuptools, no Poetry
- **🤖 Ollama** for local LLM backend (analysis, chat, and knowledge-graph extraction)
- **🔗 Zotero** for reference management — the bookmark layer; the vault is the second brain
- **⌨️ Click** for the command-line interface
- **🗂️ Flat Markdown vault** — no database; notes, sources, chats, and streams are plain `.md`/`.yaml` files
- **🔍 ChromaDB** for semantic search, running as its own supervised server process
- **🕸️ Kùzu** — embedded graph DB backing the native knowledge graph (entity/relationship extraction via structured LLM output, no third-party `graphify` dependency)
- **🌐 FastAPI + SvelteKit** — REST + WebSocket API, installable as a PWA on any platform, or wrapped in a native [Tauri desktop shell](https://github.com/CServinL/prisma-desktop)
- **🛡️ Supervised processes** — `prisma serve` runs a small supervisor that isolates the API, Web UI, ChromaDB, and knowledge-graph module into independent, crash-recoverable processes

See [Architecture Overview](docs/wiki/architecture.md) for complete technical details.

## Contributing

We welcome contributions from the community! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on:

- 🤝 [Code of Conduct](CODE_OF_CONDUCT.md)
- 📋 [Contribution Process](CONTRIBUTING.md)
- 🏛️ [Project Governance](GOVERNANCE.md)
- 🔒 [Security Policy](SECURITY.md)

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.