# Prisma
*AI-### 🔍 **Comprehensive Document Discovery**
- **Academic Papers**: Journal articles, conference papers, preprints
- **Books & Monogr### Key Features
- **📚 Multi-Document Support**: Papers, books, chapters, theses, reports, and grey literature
- **🔗 Zotero Integration**: Leverages existing research libraries and bibliographic data
- **🌐 Multi-Source Search**: Combines Zotero with external APIs for comprehensive coverage
- **📖 Full-Text Analysis**: Processes PDFs, abstracts, and metadata across all document types
- **🤖 AI-Powered Synthesis**: Uses local LLMs for cross-document analysis and comparison
- **👥 Author Analysis**: Identifies key researchers and creates academic contact directory
- **📊 Structured Output**: Generates both human-readable reports and machine-readable data*: Academic books, textbooks, reference works
- **Book Chapters**: Individual chapters from edited volumes
- **Conference Proceedings**: Full conference publications and presentations
- **Theses & Dissertations**: PhD dissertations, Master's theses
- **Reports**: Technical reports, government publications, white papers
- **Grey Literature**: Working papers, institutional reports, policy documentsriven Systematic Literature Review System*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

## Executive Abstract

**Prisma** is an AI-driven system that automates comprehensive literature reviews for academic research. Given a research topic, it searches academic databases, analyzes papers, books, conference proceedings, theses, and reports using language models, and generates comprehensive reports with key findings and recommendations.

**Core Goal:** Input a research topic (e.g., "LLMs for small, low‑power devices") → Output an executive report with synthesis, trends, gaps, and recommendations.

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

## ⚡ Development Timeline (7-Day MVP)

**Target: Working literature review tool in 1 week**

| Day | Component | Goal | Output |
|-----|-----------|------|---------|
| 1 | Infrastructure | CLI + basic file I/O | Running command interface |
| 2 | Search Agent | Single API integration (arXiv) | Paper metadata retrieval |
| 3 | Analysis Agent | Text processing basics | Abstract summarization |
| 4 | Report Agent | Markdown generation | Formatted reports |
| 5 | Author Analysis | Author extraction + directory | Research contact list |
| 6-7 | Integration | End-to-end testing | Working MVP |

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/username/prisma.git
cd prisma

# Set up Python environment with pipenv
pipenv install
pipenv shell

# Run a simple literature review (MVP target)
python -m src.coordinator --topic "machine learning" --sources "arxiv" --output "review.md"
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
- **🐍 Python 3.13.7**: Main programming language
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

## 6) Zotero Integration

Prisma works seamlessly with Zotero, the popular reference management tool, to leverage your existing research library.

### Why Zotero Integration?
- **Leverage Existing Work**: Use papers you've already collected and organized
- **Avoid Redundancy**: Don't re-download papers you already have
- **Respect Your Organization**: Maintains your existing collections and tags
- **Enhanced Coverage**: Combines your curated library with fresh external searches

### How It Works

1. **Primary Search**: Prisma searches your Zotero library first for relevant papers
2. **Gap Analysis**: Identifies missing papers by comparing with external sources
3. **External Search**: Searches arXiv, PubMed, Semantic Scholar for additional papers
4. **Optional Import**: Can add newly discovered papers back to your Zotero library

### Setup

**Find Your Zotero Database:**
- **Windows**: `%USERPROFILE%\Zotero\zotero.sqlite`
- **macOS**: `~/Zotero/zotero.sqlite`
- **Linux**: `~/Zotero/zotero.sqlite`

**Configuration:**
```yaml
sources:
  zotero:
    library_path: "/path/to/zotero.sqlite"
    collections: ["AI Research", "Edge Computing"]  # optional: specific collections
```

### Benefits for Researchers
- **Time Saving**: Don't re-analyze papers you've already read
- **Context Aware**: Builds on your existing research interests
- **Quality Control**: Leverages your curation decisions
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
**Goal**: Basic literature review automation

**Features:**
- ✅ Simple pipeline architecture (4 core components)
- ✅ Zotero integration + external API search
- ✅ LLM-based paper analysis and summarization
- ✅ Markdown report generation
- ✅ YAML configuration files
- ✅ CLI interface

**Timeline**: Q4 2024 - Q1 2025

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

### Prerequisites
1. **Python 3.13.7** with pipenv
2. **Ollama** installed with llama3.1:8b model:
   ```bash
   # Install Ollama (see https://ollama.ai)
   ollama pull llama3.1:8b
   ```

### Getting Started

1. **Clone the repository:**
   ```bash
   git clone https://github.com/CServinL/prisma.git
   cd prisma
   ```

2. **Set up development environment:**
   ```bash
   # Install pipenv if you don't have it
   pip install pipenv
   
   # Install dependencies and create virtual environment
   pipenv install --dev
   
   # Activate virtual environment
   pipenv shell
   ```

3. **Run tests:**
   ```bash
   pytest
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