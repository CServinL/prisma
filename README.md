# Prisma
*AI-Driven Systematic Literature Review System*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

## Executive Abstract

**Prisma** is an AI-driven system that automates comprehensive literature reviews for academic research. Given a research topic, it searches academic databases, analyzes papers, books, conference proceedings, theses, and reports using language models, and generates comprehensive reports with key findings and recommendations.

**Core Goal:** Input a research topic (e.g., "LLMs for small, low‑power devices") → Output an executive report with synthesis, trends, gaps, and recommendations.

### Key Features
- **📚 Multi-Document Support**: Papers, books, chapters, theses, reports, and grey literature
- **🔗 Zotero Integration**: Leverages existing research libraries and bibliographic data  
- **🌊 Research Streams**: Persistent topic monitoring with automatic discovery
- **🌐 Multi-Source Search**: Combines Zotero with external APIs for comprehensive coverage
- **📖 Full-Text Analysis**: Processes PDFs, abstracts, and metadata across all document types
- **🤖 AI-Powered Synthesis**: Uses local LLMs for cross-document analysis and comparison
- **👥 Author Analysis**: Identifies key researchers and creates academic contact directory
- **📊 Structured Output**: Generates both human-readable reports and machine-readable data

### 🔍 **Comprehensive Document Discovery**
- **Academic Papers**: Journal articles, conference papers, preprints
- **Books & Monographs**: Academic books, textbooks, reference works
- **Book Chapters**: Individual chapters from edited volumes
- **Conference Proceedings**: Full conference publications and presentations
- **Theses & Dissertations**: PhD dissertations, Master's theses
- **Reports**: Technical reports, government publications, white papers
- **Grey Literature**: Working papers, institutional reports, policy documents

**Key Features:**
- 🔍 **Smart Search**: Integrates with Zotero and academic APIs (arXiv, PubMed, Semantic Scholar)
- 🤖 **AI Analysis**: Uses local LLMs (Ollama) to summarize and analyze papers
- 📊 **Comprehensive Reports**: Generates structured markdown reports with findings and insights
- 👥 **Author Analysis**: Identifies key researchers, their contributions, and research trajectories
- 📞 **Research Directory**: Creates "telephone guide" of academics working in the field
- ⚙️ **Simple Config**: YAML configuration files for reproducible research workflows

## Contributing

We welcome contributions from the community! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on:

- 🤝 [Code of Conduct](CODE_OF_CONDUCT.md)
- 📋 [Contribution Process](CONTRIBUTING.md)
- 🏛️ [Project Governance](GOVERNANCE.md)
- 🔒 [Security Policy](SECURITY.md)

### Quick Start for Contributors

1. Read our [Code of Conduct](CODE_OF_CONDUCT.md)
2. Review [Contributing Guidelines](CONTRIBUTING.md)
3. Check out [open issues](https://github.com/CServinL/prisma/issues)
4. Join the discussion in [GitHub Discussions](https://github.com/CServinL/prisma/discussions)

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Flow](#3-data-flow)
   - 📊 [Information Flow Diagram](docs/information-flow-diagram.md)
4. [Technology Stack](#4-technology-stack)
5. [Configuration](#5-configuration)
6. [Zotero Integration](#6-zotero-integration)
7. [Roadmap](#7-roadmap)
8. [Development Setup](#8-development-setup)
   - 📖 [Complete Setup Guide](docs/development-setup.md) (WSL/Linux)

## ⚡ Development Timeline (8-Day MVP)

**Target: Working literature review tool covering core components**

| Day | Component | Goal | Output |
|-----|-----------|------|---------|
| 1 | Infrastructure | CLI + basic file I/O | ✅ Running command interface |
| 2 | Zotero Integration + Research Streams | Enhanced integration + persistent monitoring | ✅ **EXCEEDED**: Local API + Research Streams architecture |
| 3 | Multi-Source Search | arXiv + PubMed APIs | External paper discovery |
| 4 | Analysis Agent | Basic LLM integration (Ollama) | AI-powered summarization |
| 5 | Report Generation | Enhanced markdown reports | Structured literature reviews |
| 6 | Author Analysis | Research directory creation | Academic contact database |
| 7 | Integration Testing | End-to-end workflows | Validated core features |
| 8 | Polish & Documentation | Error handling + docs | Production-ready MVP |

**✅ Day 2 MAJOR ACHIEVEMENTS:**
- 🏆 **Architectural Validation**: Proved Zotero 7 Local API sufficiency
- 🌊 **Research Streams**: Revolutionary persistent topic monitoring  
- 🏗️ **Smart Organization**: Collections + Tags strategy
- 📱 **Complete CLI**: Full research stream management interface
- ⚡ **Enhanced Performance**: Local-first architecture with intelligent fallbacks

**Core Components Coverage:**
- ✅ **Zotero Integration + Research Streams** (Day 2) - **COMPLETED WITH ENHANCEMENTS**
- 🌐 **Multi-Source Search** (Day 3) 
- 🤖 **AI Analysis** (Day 4)
- 📊 **Report Generation** (Day 5)
- 👥 **Author Analysis** (Day 6)

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/username/prisma.git
cd prisma

# Set up Python environment with pipenv
pipenv install
pipenv shell

# Create a research stream for continuous monitoring
python -m src.cli.prisma_cli streams create "Neural Networks 2024" "neural networks transformer attention" --frequency weekly

# List your research streams
python -m src.cli.prisma_cli streams list

# Update all streams to find new papers
python -m src.cli.prisma_cli streams update --all

# Generate a literature review (classic approach)
python -m src.cli.prisma_cli review "machine learning" --output "ml_review.md"
```

### Research Streams in Action

```bash
# Create focused research streams
prisma streams create "AI Ethics" "artificial intelligence ethics bias fairness" --frequency weekly
prisma streams create "Quantum ML" "quantum machine learning" --frequency monthly

# Monitor and update
prisma streams summary              # Overview of all streams
prisma streams update --all         # Find new papers in all streams
prisma streams info ai-ethics      # Detailed stream information
```

### Traditional Literature Review

```bash
# See the hybrid Zotero demo
python example_hybrid_zotero.py

# Use the example configuration
cp config.hybrid.example.yaml my_research.yaml
# Edit my_research.yaml with your settings
python -m src.coordinator --config my_research.yaml
```

### What You Get
- **Executive Summary**: Key findings and trends
- **Paper Summaries**: Structured analysis of each paper
- **Comparative Analysis**: Trends, gaps, and conflicts
- **Recommendations**: Future research directions
- **Raw Data**: CSV/JSON exports for further analysis

## 2) Architecture Overview

Prisma uses a **simple pipeline architecture** with specialized components that work together to automate literature reviews.

### Core Components

**📋 Coordinator**
- Orchestrates the entire workflow
- Manages job execution and error handling
- Coordinates data flow between components

**🔍 Search Agent**
- Searches Zotero library and external APIs (arXiv, PubMed, Semantic Scholar)
- Handles deduplication and metadata normalization
- Downloads and extracts text from available PDFs

**🤖 Analysis Agent**
- Generates structured summaries for each paper
- Performs thematic classification and comparison
- Identifies trends, conflicts, and research gaps

**📊 Report Agent**
- Synthesizes findings into executive reports
- Generates markdown reports with structured insights
- Creates author analysis and research landscape mapping
- Produces comprehensive "research directory" with key academics
- Creates supplementary data files (CSV, JSON)

### Simple Data Flow
```
Config File → Search Agent → Analysis Agent → Report Agent → Results
     ↓              ↓              ↓             ↓
  Parameters    Paper PDFs    Summaries    Final Report
```

### Communication
- **Simple messaging**: Direct function calls between components
- **State storage**: SQLite database for job state and metadata
- **File-based**: Results stored as files in designated directories

## 3) Data Flow

> 📊 **Visual Guide**: See the complete [Information Flow Diagram](docs/information-flow-diagram.md) for a detailed visual representation of the system architecture.

### Simplified Pipeline

1. **Job Setup**: Coordinator reads config file and initializes job
2. **Literature Search**: Search Agent queries Zotero library and external APIs
3. **Content Processing**: Search Agent downloads PDFs and extracts text
4. **Deduplication**: Remove duplicate papers using DOI and fuzzy title matching
5. **Analysis**: Analysis Agent generates summaries and performs comparisons
6. **Synthesis**: Analysis Agent identifies themes, trends, and gaps
7. **Report Generation**: Report Agent creates final markdown report
8. **Output**: Results saved to specified directory

### Key Features
- **Zotero Integration**: Leverages existing research libraries
- **Multi-Source Search**: Combines Zotero with external APIs for comprehensive coverage
- **AI-Powered Analysis**: Uses local LLMs for paper summarization and comparison
- **Structured Output**: Generates both human-readable reports and machine-readable data

## 4) Technology Stack

### Core Technologies
- **🐍 Python 3.12+**: Main programming language (3.12.3 or higher)
- **📦 pipenv**: Dependency management and virtual environments
- **🤖 Ollama**: Local LLM backend (Llama 3.1:8b model)
- **🗃️ SQLite**: Local database for job state and metadata
- **⌨️ Typer**: Command-line interface framework

### External APIs
- **arXiv**: Physics, computer science, and mathematics papers
- **PubMed**: Biomedical literature database

### Configuration & Output
- **YAML**: Configuration files for reproducible research
- **Markdown**: Primary report format (human-readable)
- **JSON**: Structured data exports

### Why This Stack?
- **Simple**: Minimal dependencies, focused on core functionality
- **Local-first**: No cloud dependencies, works offline
- **Reproducible**: Configuration files ensure consistent results
- **Developer-friendly**: Modern Python tooling with pipenv

## 5) Configuration

Prisma uses YAML configuration files to define research parameters and ensure reproducible results.

### Basic Configuration Structure

```yaml
# prisma-config.yaml
research:
  topic: "transformer architectures for edge computing"
  keywords:
    include: ["edge AI", "mobile transformers", "quantization"]
    exclude: ["cloud computing", "datacenter"]
  date_range:
    start: "2020-01-01"
    end: "2024-12-31"

sources:
  zotero:
    library_path: "/path/to/zotero/library.sqlite"
    collections: ["AI Research", "Edge Computing"]  # optional
  external:
    arxiv: true
    pubmed: false
    semantic_scholar: true

filters:
  min_citations: 5
  max_papers: 100
  languages: ["en"]
  document_types: ["journal", "conference"]

output:
  directory: "./results/edge-ai-review-2024"
  format: "markdown"
  include_raw_data: true

execution:
  model: "llama3.1:8b"
  max_concurrent: 4
```

### Configuration Options

**Research Parameters:**
- `topic`: Main research question or area
- `keywords`: Include/exclude terms for filtering
- `date_range`: Publication date filters

**Data Sources:**
- `zotero`: Local Zotero library integration
- `external`: Enable/disable external API sources

**Output Settings:**
- `directory`: Where to save results
- `format`: Report format (currently markdown)
- `include_raw_data`: Export CSV/JSON data files

**Execution:**
- `model`: Ollama model to use for analysis
- `max_concurrent`: Number of parallel operations

## 6) Zotero Integration + Research Streams

Prisma provides **next-generation Zotero integration** with persistent research monitoring through **Research Streams** - a revolutionary approach to continuous literature discovery.

### 🚀 Major Architectural Discovery

Through comprehensive testing, we discovered that **Zotero 7's Local API provides complete functionality**, validating a streamlined desktop-primary architecture:

- ✅ **Full Library Access** via `localhost:23119/api/`
- ✅ **Advanced Search** with query parameters  
- ✅ **Write Operations** via connector endpoints
- ✅ **Collections Management** with full CRUD support
- ✅ **No API Keys Required** for local operations
- ✅ **No Rate Limits** on local access

### 🌊 Research Streams: Persistent Topic Monitoring

**Research Streams** are persistent research topics that automatically monitor for new papers using smart Zotero Collections and Tags.

#### Core Concept
```
Research Stream = Zotero Collection + Smart Tags + Auto-Monitoring
├── Collection: "Neural Networks 2024" 
├── Search Query: "neural networks transformer attention"
├── Smart Tags: prisma-auto, year-2024, type-survey
├── Auto-Refresh: Weekly
└── Continuous Discovery: New papers → Auto-tagged → Added to collection
```

#### CLI Interface
```bash
# Create a new research stream
prisma streams create "Neural Networks 2024" "neural networks transformer" --frequency weekly

# List all active streams
prisma streams list --status active

# Update all streams to find new papers  
prisma streams update --all

# Get detailed stream information
prisma streams info neural-networks-2024

# System overview
prisma streams summary
```

### 🏗️ Smart Collections + Tags Strategy

**📁 Collections = Research Topics**
- Hierarchical organization by research area
- Examples: `Neural Networks/Transformers`, `AI Ethics`, `Quantum ML`
- Each stream creates a dedicated Zotero collection

**🏷️ Tags = Cross-cutting Metadata**
- **Prisma Tags**: `prisma-[stream-id]`, `prisma-auto`
- **Temporal Tags**: `year-2024`, `recent`, `foundational`  
- **Methodology Tags**: `survey`, `empirical`, `theoretical`
- **Status Tags**: `to-read`, `key-paper`, `cited-in-report`
- **Quality Tags**: `high-impact`, `peer-reviewed`

### Integration Modes

#### 1. Enhanced Local API (Recommended - Zotero 7+)
Uses Zotero 7's full local HTTP API for optimal performance:

```yaml
sources:
  zotero:
    mode: "local_api"
    server_url: "http://127.0.0.1:23119"  # Zotero 7 local server
    collections: ["AI Research", "Edge Computing"]
```

#### 2. Hybrid Integration (Maximum Compatibility)
Combines Local API, SQLite, and Web API with intelligent fallbacks:

```yaml
sources:
  zotero:
    mode: "hybrid"
    library_path: "/path/to/zotero.sqlite"
    api_key: "your_zotero_api_key"  # optional
    user_id: "your_user_id"  # optional
    enable_desktop_save: true
    collections: ["AI Research", "Edge Computing"]
```

#### 3. SQLite Only (Fast, Offline)
Direct database access for maximum speed:

```yaml
sources:
  zotero:
    mode: "sqlite"
    library_path: "/path/to/zotero.sqlite"
    collections: ["AI Research", "Edge Computing"]
```

### 📊 Recommended Architecture

1. **🎯 PRIMARY**: Zotero Local API (`localhost:23119/api/`) for reads
2. **💾 WRITES**: Zotero Connector (`localhost:23119/connector/`) for saves  
3. **🌐 DISCOVERY**: Web API for finding NEW papers not in local library
4. **📚 ORGANIZATION**: Research Streams for persistent monitoring
5. **🔄 FALLBACK**: SQLite when local API unavailable

### Research Streams Workflow

1. **Create Stream**: Define research topic and search criteria
2. **Initial Population**: Search and save relevant papers to collection
3. **Continuous Monitoring**: Periodic searches for new papers
4. **Smart Tagging**: Automatic categorization and metadata assignment
5. **Report Generation**: Analyze stream contents for literature reviews

### Key Benefits

- **🔒 100% Zotero Compatible**: Uses official APIs and connector endpoints
- **⚡ Lightning Fast**: Local API eliminates network latency
- **� Continuous Discovery**: Research streams monitor topics over time
- **� Smart Organization**: Collections + Tags enable flexible querying
- **🎯 Targeted Research**: Stream-specific monitoring with deduplication
- **🔄 Perfect Sync**: All operations maintain Zotero sync integrity
- **📱 Cross-Platform**: Works with Zotero on Windows, Mac, and Linux
- **Workflow Integration**: Fits into existing research practices

## 7) Permissions Model (OA vs Non‑OA)

- **OA papers** → summaries public
- **Non‑OA PDFs** uploaded by a licensed user → full processing stored as private (owner/group visibility)
- **Reports**: public baseline (abstract‑only for Non‑OA) + private enrichment for owners/groups

## 8) Legal/Data Strategies

- **Prefer OA sources**: arXiv, PubMed Central, bioRxiv/medRxiv, DOAJ
- **Metadata enrichment**: CrossRef, Semantic Scholar
- **Closed publishers**: do not auto‑download PDFs; store metadata + abstract
- **Store DOI/URL/license**; maintain audit logs of sources and licenses

## 9) Prompts (conceptual)

- **Per‑paper summary**: extract objectives, methods, datasets, metrics, results, limitations (structured JSON)
- **Meta‑summary**: panorama, subtopics, comparisons, common limitations, gaps, recommendations (cite paper IDs/DOIs)

## 10) MVP Code Skeleton (conceptual only)

**Sequential pipeline**: Manager → Search → Fetch/Extract → Summarize → Classify → Synthesize → Report

Replace mocks with real connectors later; route LLM calls via Ollama when implemented

## 11) Configuration-Driven User Interface

### Phase 0 Interaction Model
Prisma operates as a **file-based system** with no web interface initially, prioritizing simplicity and reliability.

### Configuration Files
```yaml
# prisma-config.yaml
research:
  topic: "transformer architectures for edge computing"
  keywords:
    include: ["edge AI", "mobile transformers", "quantization"]
    exclude: ["cloud computing", "datacenter"]
  date_range:
    start: "2020-01-01"
    end: "2024-12-31"
  
sources:
  zotero:
    library_path: "/home/user/.zotero/zotero.sqlite"
    collections: ["AI Research", "Edge Computing"]
  external:
    arxiv: true
    pubmed: false
    semantic_scholar: true
    
filters:
  min_citations: 5
  languages: ["en"]
  document_types: ["journal", "conference"]

output:
  directory: "./results/edge-ai-review-2024"
  formats: ["markdown", "json", "csv"]
  include_pdfs: true
  
execution:
  max_papers: 500
  parallel_agents: 4
  model: "llama3.1:8b"
```

### CLI Interface
```bash
# Submit new job
prisma submit --config ./configs/edge-ai-review.yaml

# Check job status
prisma status --job edge-ai-review-2024

# List all jobs
prisma list

# View logs
prisma logs --job edge-ai-review-2024 --tail

# Cancel running job
prisma cancel --job edge-ai-review-2024
```

### File System Structure
```
prisma-workspace/
├── configs/           # User configuration files
├── jobs/             # Active job tracking
├── results/          # Generated reports and artifacts
├── logs/             # Execution logs
├── cache/            # API response cache
└── models/           # Local model storage
```

### Benefits of Config-Driven Approach
- **Version control**: Configurations can be tracked in git
- **Reproducibility**: Exact parameters preserved for replication
- **Batch processing**: Multiple jobs easily queued
- **Automation**: Integration with CI/CD pipelines
- **Simplicity**: No web server dependencies or UI complexity

## 12) Monitoring & Metrics

### Coverage
- OA/Non‑OA counts, source coverage %, year distribution

### Performance
- Latency per stage, throughput (papers/min), token usage

### Quality
- Hallucination checks via DOI cross‑verification; consistency checks; low‑confidence flags

### Audit
- Per‑paper logs (source, license, processed_at, owner if private)

## 13) Risks & Mitigations

- **Legal**: restrict Non‑OA content to private visibility for owners/groups
- **Performance**: cap concurrency for large models; avoid frequent model swaps
- **Data quality**: DOI/author normalization; dedup (DOI + fuzzy title)
- **Robustness**: retry/backoff for APIs; local metadata cache

## 7) Roadmap

### Phase 0: Core MVP (Current Focus)
**Goal**: Basic literature review automation with all core components

**Features:**
- ✅ Simple pipeline architecture (4 core components)
- 🔄 Zotero integration + external API search (Day 2-3)
- 🔄 LLM-based paper analysis and summarization (Day 4)
- ✅ Markdown report generation (Enhanced Day 5)
- ✅ YAML configuration files  
- ✅ CLI interface
- 🔄 Author analysis and research directory (Day 6)

**Timeline**: Q4 2024 - Q1 2025 (8-day intensive MVP)

### Phase 1: Enhanced Analysis (Next)
**Goal**: Improve analysis quality and user experience

**Features:**
- 📊 Better comparative analysis and trend detection
- 🎯 Improved deduplication and metadata handling
- 📄 Multiple output formats (HTML, PDF export)
- ⚡ Performance optimizations
- 🔧 Enhanced CLI with better error handling

**Timeline**: Q2-Q3 2025

### Phase 2: Collaborative Features (Future)
**Goal**: Multi-user workflows and advanced features

**Features:**
- 🌐 Optional web interface for report viewing
- 👥 Shared research projects and collaboration
- 🔄 Scheduled review updates
- 📈 Advanced analytics and visualizations
- 🔌 API endpoints for integration

**Timeline**: Q4 2025 - Q1 2026

### Development Principles
- **MVP First**: Get core functionality working before adding features
- **User-Driven**: Features based on real researcher needs
- **Simple by Default**: Complex features are optional, not required
- **Academic Integrity**: Maintain research quality and reproducibility standards

### Future Enhancements (Post-MVP)

**Priority: Get working MVP in 7 days, then iterate based on user feedback**

#### 📅 **Week 2: Critical Improvements** 
- **Multiple APIs**: Add PubMed, Semantic Scholar integration
- **Book Support**: ISBN lookup, library catalogs, Google Books API
- **Document Processing**: PDF full-text extraction and analysis
- **LLM Analysis**: Local model integration for semantic analysis  
- **Better Export**: LaTeX and Word format support
- **Performance**: Concurrent processing and caching

#### 📅 **Month 2: Advanced Features**
- **Reference Managers**: Mendeley, EndNote, RefWorks integration
- **Grey Literature**: Technical reports, theses, government publications
- **Team Collaboration**: Shared projects and multi-user support
- **Conference Proceedings**: Full conference database integration
- **Advanced Analytics**: Citation impact and trend analysis

#### 🔍 **Expanded Search Scope**
- **Additional Databases**: Semantic Scholar, IEEE Xplore, JSTOR, Web of Science
- **Cross-domain Search**: Multi-disciplinary research support across all major databases
- **Advanced Filtering**: Institution-based, author-based, and citation-based filtering
- **Search Optimization**: Smarter query expansion and result ranking

#### 📚 **Non-Open Access Support**
- **Institutional Access**: Integration with university library systems
- **Publisher APIs**: Direct integration with major academic publishers
- **Access Management**: Handle subscription-based and paywall content
- **Fair Use Compliance**: Automated compliance with academic use policies

#### ⚡ **Parallel Processing & Performance**
- **Concurrent Search**: Search multiple databases simultaneously
- **Parallel Analysis**: Process multiple papers concurrently with LLM batching
- **Distributed Processing**: Scale across multiple machines for large reviews
- **Caching & Resume**: Smart caching and ability to resume interrupted reviews

#### 🔄 **Automated Updates & Monitoring**
- **Scheduled Reviews**: Automatic updates to existing literature reviews
- **"What's New" Reports**: Highlight changes between report versions with visual diff
- **Delta Analysis**: Show new papers, updated citations, and emerging trends since last review
- **Change Notifications**: Alert system when new relevant papers are published
- **Trend Monitoring**: Track emerging topics and research directions over time
- **Version Control**: Maintain history of review updates and changes
- **Smart Incremental Updates**: Only re-analyze changed or new content to save time

#### 🌐 **Advanced Integration**
- **Reference Managers**: Deep integration with Mendeley, EndNote, RefWorks
- **Citation Networks**: Analyze citation patterns and research impact
- **Collaboration Tools**: Team-based research projects and shared reviews
- **Export Formats**: LaTeX, Word, EndNote, and journal-specific formats

#### � **Author Intelligence & Research Mapping**
- **Comprehensive Author Profiles**: Detailed profiles of key researchers in the field
- **Research Trajectories**: Track how authors' research has evolved over time
- **Collaboration Networks**: Map co-authorship patterns and research partnerships
- **Institution Mapping**: Identify leading research institutions and departments
- **Contact Directory**: Academic "telephone guide" with affiliations and contact information
- **Expertise Classification**: Categorize authors by research specializations and methodologies
- **Publication Analytics**: Author productivity, citation impact, and influence metrics
- **Research Timeline**: Chronological view of each author's contributions to the field
- **Emerging Researchers**: Identify up-and-coming scholars and recent PhD graduates
- **Geographic Distribution**: Map research activity by country and region

#### �📊 **Visual Analytics & Reference Mapping**
- **ConnectedPapers Integration**: Generate ConnectedPapers.com links for citation network visualization
- **One-click Network View**: Auto-generate ConnectedPapers URLs using DOIs or paper identifiers
- **Batch Link Generation**: Create ConnectedPapers links for multiple key papers simultaneously  
- **Report Embedding**: Include ConnectedPapers links directly in markdown literature review reports
- **Discovery Workflow**: Use ConnectedPapers to explore networks → Import relevant papers back to Prisma
- **Multi-origin Networks**: Leverage ConnectedPapers' multi-origin graphs for comprehensive field views
- **Prior/Derivative Works**: Link to ConnectedPapers' prior and derivative work views for temporal analysis

*Note: ConnectedPapers does not currently offer a public API, but we can generate direct links to their service using paper DOIs, arXiv IDs, or Semantic Scholar URLs for seamless integration.*

*Note: These features represent potential directions based on user feedback and academic research needs. The core philosophy remains simplicity and reliability first.*

## 8) Development Setup

> **📖 Complete Setup Guide**: See [docs/development-setup.md](docs/development-setup.md) for detailed WSL/Linux setup instructions covering Zotero, Ollama, and Prisma configuration.

### Quick Start (Prerequisites Required)

**Prerequisites:**
1. **Python 3.12+** with pipenv 
2. **Ollama** installed with llama3.1:8b model
3. **Zotero** with research library (optional for basic testing)

### Basic Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/CServinL/prisma.git
   cd prisma
   ```

2. **Set up development environment:**
   ```bash
   # Install pipenv if you don't have it
   pipx install pipenv
   
   # Install dependencies and create virtual environment
   pipenv install --dev
   
   # Activate virtual environment
   pipenv shell
   ```

3. **Test basic functionality:**
   ```bash
   # Test CLI interface
   python src/cli/main.py --help
   
   # Run simple literature review (Day 1 MVP)
   python src/cli/main.py --topic "machine learning" --limit 3
   ```
   ```

4. **Try a simple example:**
   ```bash
   python -m src.cli.main start examples/simple-review.yaml
   ```

### Project Structure
```
prisma/
├── src/                # Main source code
│   ├── coordinator.py  # Main pipeline controller
│   ├── agents/         # Search, analysis, and report agents  
│   ├── integrations/   # External API connectors
│   ├── storage/        # SQLite database layer
│   ├── cli/           # Command-line interface
│   └── utils/         # Configuration and logging
├── tests/             # Test suite
├── config/            # Configuration templates
└── docs/             # Documentation and ADRs
```

### Contributing
See our [Contributing Guidelines](CONTRIBUTING.md) for development workflow, coding standards, and how to submit pull requests.

---

---

## 📚 Project Governance

This project follows a structured governance model to ensure quality, sustainability, and community collaboration:

### 📋 Documentation
- **[Governance Model](GOVERNANCE.md)** - Project structure, roles, and decision-making processes
- **[Contributing Guidelines](CONTRIBUTING.md)** - How to contribute effectively
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Community standards and behavior expectations
- **[Security Policy](SECURITY.md)** - Security practices and vulnerability reporting

### 🏛️ Project Structure
- **Project Lead**: @CServinL
- **Core Maintainers**: To be established as project grows
- **Subject Matter Experts**: Academic research methodology, NLP, research ethics
- **Contributors**: Community developers and researchers

### 🔄 Development Process
- **Linear History**: All changes via pull requests with linear git history
- **Code Review**: Mandatory review by maintainers
- **Testing**: Comprehensive testing requirements
- **Documentation**: Keep documentation current with changes

### 🤝 Community
- **Open Development**: Transparent development process
- **Academic Integrity**: Maintain highest research ethics standards
- **Inclusive Environment**: Welcome diverse perspectives and contributors
- **Quality Focus**: Prioritize reliability and academic rigor

### 📞 Getting Help
- **Issues**: [GitHub Issues](https://github.com/CServinL/prisma/issues) for bugs and features
- **Discussions**: [GitHub Discussions](https://github.com/CServinL/prisma/discussions) for questions
- **Security**: See [Security Policy](SECURITY.md) for security-related concerns

---

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Contributors and maintainers who make this project possible
- The academic research community for guidance and requirements
- Open source projects and tools that enable this work