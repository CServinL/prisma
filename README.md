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

```bash
# Clone and install
git clone https://github.com/CServinL/prisma.git
cd prisma
poetry install

# Create your first research stream for library management
poetry run prisma streams create "AI Research" "artificial intelligence machine learning" --frequency weekly

# List and update streams
poetry run prisma streams list
poetry run prisma streams update --all
```

## Documentation

### Getting Started
- 🚀 **[Quick Start Guide](docs/quick-start.md)** - Get up and running in minutes
- 🌊 **[Research Streams Guide](docs/research-streams-guide.md)** - Complete streams documentation
- 🔧 **[Development Setup](docs/development-setup.md)** - Full development environment setup

### Core Features
- 🏗️ **[Architecture Overview](docs/architecture.md)** - System design and data flow
- ⚙️ **[Configuration Guide](docs/configuration.md)** - YAML configuration and options
- 🔗 **[Zotero Integration](docs/zotero-integration.md)** - Complete Zotero setup and usage
- ⭐ **[Quality Rating System](docs/rating-system.md)** - Source quality management and academic validation
- 📖 **[CLI Documentation](docs/cli.md)** - Complete command-line interface reference

### Development
- 📅 **[Development Timeline](docs/development-timeline.md)** - 8-day MVP progress
- 🗺️ **[Roadmap](docs/roadmap.md)** - Future features and phases
- 🏛️ **[Architecture Decision Records](docs/)** - Technical decisions and rationale

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