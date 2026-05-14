# Prisma
*Research Library Assistant with Zotero Integration*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

## Overview

**Prisma** is a Research Library Assistant that helps researchers intelligently organize, curate, and enhance their research libraries using **Zotero as the primary organization tool**. It discovers research content, assesses relevance, and provides intelligent library management.

**Architecture:** CLI → Coordinator → Source Integrations (External APIs + Zotero Libraries) → Zotero Storage → LLM Analysis → Library Enhancement

## System Requirements

**Required (Offline):**
- **Zotero Desktop** with Local HTTP API enabled (library management operations)
- **Ollama** with local LLM (research analysis and curation)

**Optional (Online):**
- **Zotero Web API** access (for discovering and saving new research)
- **Internet** access to source APIs (arXiv, Semantic Scholar, etc.)

## Key Features

- **📚 Multi-Document Support**: Papers, books, chapters, theses, reports, and grey literature
- **🔗 Zotero Integration**: Leverages existing research libraries and bibliographic data  
- **🌊 Research Streams**: Persistent topic monitoring with automatic discovery and organization
- **⭐ Quality-Based Sources**: 1-5 star rating system prioritizing reliable academic databases
- **🛡️ Academic Validation**: Filters out non-academic content with confidence scoring
- **🌐 Multi-Source Search**: Combines premium APIs with structured data sources
- **📖 Full-Text Analysis**: Processes PDFs, abstracts, and metadata across all document types
- **🤖 AI-Powered Curation**: Uses local LLMs for intelligent research assessment and organization
- **👥 Author Analysis**: Identifies key researchers and creates academic contact directory
- **📊 Library Organization**: Generates structured research organization and enhanced library management

## Research Library Management Process

**Prisma's research library management workflow:**

1. **Discover Research** - Query external APIs and Zotero libraries using stream's search criteria
   - **External Sources**: arXiv, Semantic Scholar, PubMed, etc.
   - **Zotero Libraries**: Existing research collections and newly imported items
2. **Assess Relevance** - Use LLM to quickly evaluate research relevance to the topic
3. **Curate Content** - Filter and organize relevant research immediately
4. **For Relevant Research:**
   - **Check Zotero Storage** - Search local Zotero library for duplicates (offline HTTP API)
   - **Save to Zotero** - Store new research and add to stream collection (if online)
   - **Mark Unsaved** - Flag research that couldn't be saved (if offline)
5. **Analyze Content** - Comprehensive LLM analysis for research assessment
6. **Enhance Library** - Improve organization and provide research insights (noting any unsaved research)

**Note**: Zotero serves dual roles as both a **source integration** (for discovering existing relevant research) and **primary organization tool** (for organizing and managing research collections).

## CLI Commands

> 📖 **Complete CLI Reference**: See [CLI Documentation](docs/cli.md) for detailed command options, examples, and advanced usage.

### Research Streams
```bash
# Create a new research stream
prisma streams create "Stream Name" "search query" --frequency weekly

# List all streams
prisma streams list

# Update streams (find new papers)
prisma streams update --all
prisma streams update stream-id --force

# Get stream details
prisma streams info stream-id
```

### Research Analysis
```bash
# Generate research analysis
prisma review "neural networks" --output report.md

# Use specific sources
prisma review "AI ethics" --sources arxiv,scholar --limit 50

# Zotero-only mode
prisma review "machine learning" --zotero-only
```

### System Management
```bash
# Check system status
prisma status --verbose

# Zotero integration
prisma zotero test-connection
prisma zotero list-collections
```

## Quick Start

### Regular users (install from PyPI)

```bash
pip install prisma
prisma streams create "AI Research" "artificial intelligence machine learning" --frequency weekly
prisma streams list
prisma streams update --all
```

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
- [Zotero Integration](docs/wiki/zotero.md) — read/write split, offline mode
- [Architecture](docs/wiki/architecture.md) — components and data flow
- [Roadmap](docs/wiki/roadmap.md) — planned features

## Technology Stack

- **🐍 Python 3.12+** with Poetry for dependency management
- **🤖 Ollama** for local LLM backend (Llama 3.1:8b)
- **🔗 Zotero** for reference management and organization
- **⌨️ Click** for command-line interface
- **🗃️ SQLite** for local database and job state

See [Architecture Overview](docs/architecture.md) for complete technical details.

## Contributing

We welcome contributions from the community! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on:

- 🤝 [Code of Conduct](CODE_OF_CONDUCT.md)
- 📋 [Contribution Process](CONTRIBUTING.md)
- 🏛️ [Project Governance](GOVERNANCE.md)
- 🔒 [Security Policy](SECURITY.md)

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.