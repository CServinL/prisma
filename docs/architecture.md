# Architecture Overview

Prisma uses a **simple pipeline architecture** with specialized components that work together to automate literature reviews.

## Core Components

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

## Simple Data Flow
```
Config File → Search Agent → Analysis Agent → Report Agent → Results
     ↓              ↓              ↓             ↓
  Parameters    Paper PDFs    Summaries    Final Report
```

## Communication
- **Simple messaging**: Direct function calls between components
- **State storage**: SQLite database for job state and metadata
- **File-based**: Results stored as files in designated directories

## Data Flow Pipeline

> 📊 **Visual Guide**: See the complete [Information Flow Diagram](information-flow-diagram.md) for a detailed visual representation of the system architecture.

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

## Technology Stack

### Core Technologies
- **🐍 Python 3.12+**: Main programming language (3.12.3 or higher)
- **📦 Poetry**: Modern dependency management and virtual environments
- **🤖 Ollama**: Local LLM backend (Llama 3.1:8b model)
- **🗃️ SQLite**: Local database for job state and metadata
- **⌨️ Click**: Command-line interface framework

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
- **Developer-friendly**: Modern Python tooling with Poetry

## Project Structure
```
prisma/
├── prisma/             # Main source code (renamed from src/)
│   ├── coordinator.py  # Main pipeline controller
│   ├── agents/         # Search, analysis, and report agents  
│   ├── integrations/   # External API connectors
│   ├── storage/        # SQLite database layer
│   ├── cli/           # Command-line interface
│   └── utils/         # Configuration and logging
├── tests/             # Test suite
├── config/            # Configuration templates
├── docs/             # Documentation and ADRs
├── data/             # Research streams (git ignored)
└── outputs/          # Generated reports
```