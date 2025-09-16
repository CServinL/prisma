# Source Code

This directory contains all source code for the Prisma literature review system.

**For complete folder structure documentation, see:** [`docs/ADR-006-simple-folder-structure.md`](../docs/ADR-006-simple-folder-structure.md)

## Current Structure

```
src/
├── coordinator.py              # Main pipeline controller
├── agents/                     # 3 core agents  
│   ├── search_agent.py        #   Paper search (PubMed, ArXiv)
│   ├── analysis_agent.py      #   LLM analysis with Ollama
│   ├── report_agent.py        #   Report generation
│   └── __init__.py            #   Agent imports
├── cli/                       # Typer command-line interface
├── integrations/              # External API connections
│   ├── llm/                   #   Ollama integration
│   ├── external_apis/         #   PubMed, ArXiv APIs
│   └── ...                    #   Other integrations
├── storage/                   # Data persistence
│   ├── models/                #   Data models
│   └── ...                    #   Database operations
└── utils/                     # Shared utilities
    ├── config.py              #   Configuration loading
    └── logging.py             #   Logging setup
```

## Development Priority

Build components in this order:
1. **`cli/main.py`** - Basic Typer CLI structure  
2. **`coordinator.py`** - Main pipeline logic (✅ created)
3. **`agents/search_agent.py`** - PubMed/ArXiv search (✅ created)
4. **`agents/analysis_agent.py`** - Ollama integration (✅ created)
5. **`agents/report_agent.py`** - Markdown generation (✅ created)
6. **`storage/database.py`** - SQLite operations
7. **`utils/config.py`** - YAML configuration loading

## Key Design Principles

- **Simple direct calls**: No complex messaging or orchestration
- **Linear pipeline**: Search → Analysis → Report
- **SQLite state**: Job status and progress tracking
- **YAML configuration**: Easy research workflow setup
- **Modern Python**: Python 3.13.7 with pipenv for dependency management
- **Minimal dependencies**: Python + Ollama + SQLite + Typer