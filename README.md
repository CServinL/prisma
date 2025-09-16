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
- **� Quality-Based Sources**: 1-5 star rating system prioritizing reliable academic databases
- **🛡️ Academic Validation**: Filters out non-academic content with confidence scoring
- **🌐 Multi-Source Search**: Combines premium APIs with structured data sources
- **📖 Full-Text Analysis**: Processes PDFs, abstracts, and metadata across all document types
- **🤖 AI-Powered Synthesis**: Uses local LLMs for cross-document analysis and comparison
- **👥 Author Analysis**: Identifies key researchers and creates academic contact directory
- **📊 Structured Output**: Generates both human-readable reports and machine-readable data

### 🌟 **Quality-Based Source Management**

Prisma uses a **1-5 star rating system** to ensure high-quality academic content:

- **⭐⭐⭐⭐⭐ (5-star)**: Premium APIs with curated content
  - **Semantic Scholar**: AI-powered search with 214M+ papers
  - **arXiv**: High-quality preprint server with full metadata

- **⭐⭐⭐⭐ (4-star)**: Good APIs with structured data  
  - **Open Library**: Internet Archive's millions of academic books
  - **Google Books**: Comprehensive book catalog with rich metadata

- **⭐⭐⭐ (3-star)**: Basic APIs and reliable sources
  - **Zotero**: User's personal research library

**Academic Validation**: Automatically filters content requiring authors, venues, and proper academic indicators while excluding blog posts, news articles, and social media content.

### 🔍 **Comprehensive Document Discovery**
- **Academic Papers**: Journal articles, conference papers, preprints
- **Books & Monographs**: Academic books, textbooks, reference works
- **Book Chapters**: Individual chapters from edited volumes
- **Conference Proceedings**: Full conference publications and presentations
- **Theses & Dissertations**: PhD dissertations, Master's theses
- **Reports**: Technical reports, government publications, white papers
- **Grey Literature**: Working papers, institutional reports, policy documents

## 🚀 Quick Start

```bash
# Clone and install
git clone https://github.com/CServinL/prisma.git
cd prisma
poetry install

# Create your first research stream
poetry run prisma streams create "AI Research" "artificial intelligence machine learning" --frequency weekly

# List and update streams
poetry run prisma streams list
poetry run prisma streams update --all
```

## 📖 Documentation

### Getting Started
- 🚀 **[Quick Start Guide](docs/quick-start.md)** - Get up and running in minutes
- 🌊 **[Research Streams Guide](docs/research-streams-guide.md)** - Complete streams documentation
- 🔧 **[Development Setup](docs/development-setup.md)** - Full development environment setup

### Core Features
- 🏗️ **[Architecture Overview](docs/architecture.md)** - System design and data flow
- ⚙️ **[Configuration Guide](docs/configuration.md)** - YAML configuration and options
- 🔗 **[Zotero Integration](docs/zotero-integration.md)** - Complete Zotero setup and usage

### Development
- 📅 **[Development Timeline](docs/development-timeline.md)** - 8-day MVP progress
- 🗺️ **[Roadmap](docs/roadmap.md)** - Future features and phases
- 🏛️ **[Architecture Decision Records](docs/)** - Technical decisions and rationale

## ⚡ Development Status

**Current**: Day 2 - Research Streams ✅ **COMPLETED WITH ENHANCEMENTS**

| Status | Component | Description |
|--------|-----------|-------------|
| ✅ | **Infrastructure** | CLI + basic file I/O |
| ✅ | **Research Streams** | Revolutionary persistent topic monitoring |
| 🔄 | **Multi-Source Search** | arXiv + PubMed APIs integration |
| 🔄 | **AI Analysis** | LLM integration (Ollama) |
| 🔄 | **Report Generation** | Enhanced markdown reports |
| 🔄 | **Author Analysis** | Research directory creation |

See [Development Timeline](docs/development-timeline.md) for detailed progress.

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

## Technology Stack

- **🐍 Python 3.12+** with Poetry for dependency management
- **🤖 Ollama** for local LLM backend (Llama 3.1:8b)
- **🔗 Zotero** for reference management and organization
- **⌨️ Click** for command-line interface
- **🗃️ SQLite** for local database and job state

See [Architecture Overview](docs/architecture.md) for complete technical details.

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

### 📞 Getting Help
- **Issues**: [GitHub Issues](https://github.com/CServinL/prisma/issues) for bugs and features
- **Discussions**: [GitHub Discussions](https://github.com/CServinL/prisma/discussions) for questions
- **Security**: See [Security Policy](SECURITY.md) for security-related concerns

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Contributors and maintainers who make this project possible
- The academic research community for guidance and requirements
- Open source projects and tools that enable this work