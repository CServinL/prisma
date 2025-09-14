# Prisma
*AI-Driven Systematic Literature Review System*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

## Executive Abstract

This document defines the master plan for **Prisma**, an AI‑driven swarm of specialized agents that collaborate to perform systematic literature reviews in academic research. It outlines the overall scope, architecture, workflows, deployment setups, integration with reference managers, permissions for open‑access vs non‑open‑access content, scheduled refresh capabilities, investigator summaries, and notification systems. The plan establishes the foundation for building a reproducible, ethical, and scalable system that can continuously synthesize the current state of research on any given topic, supporting both individual investigators and research teams.

**Goal:** Given a research topic (e.g., current state of research on LLMs for small, low‑power devices), the swarm searches, filters, summarizes, classifies, compares, performs methodological critique, and produces an executive report with recommendations.

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

1. [Scope and Deliverables](#1-scope-and-deliverables)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Flow](#3-data-flow)
4. [Stack](#4-stack)
5. [Deployment Setups](#5-deployment-setups)
6. [Zotero Integration](#6-zotero-integration)
7. [Permissions Model (OA vs Non‑OA)](#7-permissions-model-oa-vs-non-oa)
8. [Legal/Data Strategies](#8-legaldata-strategies)
9. [Prompts (conceptual)](#9-prompts-conceptual)
10. [MVP Code Skeleton (conceptual only)](#10-mvp-code-skeleton-conceptual-only)
11. [Configuration-Driven User Interface](#11-configuration-driven-user-interface)
12. [Monitoring & Metrics](#12-monitoring--metrics)
13. [Risks & Mitigations](#13-risks--mitigations)
14. [Roadmap](#14-roadmap)
15. [How to Run MVP (conceptual)](#15-how-to-run-mvp-conceptual)
16. [Pending Decisions](#16-pending-decisions)
17. [Investigator Summary in Reports](#17-investigator-summary-in-reports)
18. [Saved Job Config & Scheduled Refresh](#18-saved-job-config--scheduled-refresh)
19. [Notification System](#19-notification-system)
20. [API Endpoints (planned)](#20-api-endpoints-planned)
21. [Data Model Extensions](#21-data-model-extensions)
22. [Scheduling & Execution Notes](#22-scheduling--execution-notes)
23. [Security & Privacy](#23-security--privacy)
24. [API Rate Limits & Throttling](#24-api-rate-limits--throttling-documented-policies)
25. [References](#25-references)

## 1) Scope and Deliverables

### Input
- **Configuration file** (YAML/JSON): research topic/query, parameters, filters
- **Parameters**: date ranges, sources (arXiv, PubMed, Semantic Scholar), minimum citations, include/exclude keywords
- **Zotero library path** or connection details

### Output
- **Executive report** (Markdown/HTML files): synthesis, key findings, topic map, comparison tables, gaps, future research directions
- **Auxiliary artifacts**: CSV with metadata, JSON of per‑paper summaries, vector index for semantic search
- **Log files**: execution logs, error reports, processing statistics

### User Interaction Model (Phase 0)
- **Config-driven**: Users create configuration files specifying research parameters
- **File-based output**: Results delivered as files in designated output directories
- **Command-line execution**: Run via CLI commands or scheduled execution
- **No web UI**: Direct file system interaction for input/output

## 2) Architecture Overview

### Manager/Planner
Orchestrates workflow, distributes tasks, handles retries/errors

### Specialized Agents (parallelizable):
- **Zotero Query Agent** (primary search in user's library)
- **External Searchers** (arXiv/PubMed/Semantic Scholar for gaps)
- **Zotero Import Agent** (auto-import discovered papers)
- **Deduplicator & Metadata Normalizer**
- **PDF Fetcher & Text Extractor** (abstract, methods, results, discussion)
- **Summarizers** (homogeneous per‑paper summaries)
- **Thematic Classifier** (topic clustering/taxonomy)
- **Comparator** (similarities, conflicts, benchmarks, gaps)
- **Methodology Critic** (sample sizes, biases, validity)
- **Synthesizer** (meta‑summary + visuals)
- **Evaluator** (quality control, coherence, reference checking)
- **Report Builder** (Markdown/HTML)

### Communication
Message bus (in‑memory queue), metadata/state in relational DB + vector index

## 3) Data Flow

1. Manager receives topic, creates job
2. **Zotero Query Agent** searches user's library first
3. **External Searchers** query APIs for missing papers (in parallel)
4. **Zotero Import Agent** adds newly discovered papers to user's library
5. **Deduplicator** normalizes records and removes duplicates across all sources
6. **Fetchers** download OA PDFs / extract text (prioritizing Zotero-stored PDFs)
7. **Summarizers** produce normalized summaries
8. **Thematic Classifier** groups into subtopics
9. **Comparator** detects trends/conflicts/gaps
10. **Methodology Critic** reviews methodological quality
11. **Synthesizer** builds global narrative
12. **Evaluator** validates coherence and references
13. **Report Builder** compiles the final document

## 4) Stack

- **LLM backend**: Ollama (e.g., Llama 3.1 8B/70B, Mistral 7B, Qwen)
- **Orchestration**: AirFlow for workflow management and scheduling; CrewAI/AutoGen/LangChain for agent coordination
- **Scaling**: Ray/Dask for parallel processing
- **Vector DB**: FAISS or Chroma (local)
- **Database**: SQLite or Postgres
- **PDF/Text extraction**: PyMuPDF, pdfminer.six; GROBID optional for scholarly metadata
- **Configuration**: YAML/JSON config files for job definitions
- **CLI interface**: Command-line tools for job submission and monitoring
- **Optional model routing**: see RouteLLM APIs (unified gateway)

## 5) Deployment Setups

### Setup A – Local GPU (RTX 4090M, 16 GB VRAM)
- One efficient base model (e.g., Llama 3.1 8B Q4 or Mistral 7B Q4) loaded in Ollama
- 3–6 concurrent agents share the same model (prompt‑based role differentiation)
- **Trade‑off**: fast and consistent; less depth than 70B for critique/synthesis
- **Use case**: personal research, MVP prototyping

### Setup B – High‑end Node (EVO‑X2, 128 GB VRAM)
- Concurrent models: 8B for batch/parallel; 70B for deep critique/synthesis
- 20+ agents for 8B; 1–2 for 70B
- **Use case**: research teams, production‑grade reports

## 6) Zotero Integration

### Primary Strategy: Zotero as Core Database
Zotero serves as our **primary source** for paper metadata, PDFs, and bibliographic management. Prisma will leverage Zotero's existing infrastructure and user collections as the foundation.

### Integration Methods:
- **Web API** (multi‑user, cloud sync) — API key required, best for team collaboration
- **SQLite local** (fast, offline, private) — direct database access for individual researchers
- **Connector API** (BetterBibTeX export via local connector) — seamless bibliography export

### Hybrid Approach: Zotero + External APIs
Since Zotero won't contain every paper, Prisma implements a **cascading search strategy**:

1. **Primary**: Search user's Zotero library first (fastest, most relevant to user's research)
2. **Secondary**: Query external APIs (arXiv, PubMed, Semantic Scholar) for missing papers
3. **Integration**: Auto-import discovered papers back into Zotero for future use
4. **Deduplication**: Cross-reference DOIs/titles between Zotero and external sources

### Implementation Strategy:
- **MVP**: SQLite local access + external API fallback
- **Production**: Web API for teams + enhanced auto-import workflows
- **Advanced**: Real-time sync between Prisma discoveries and user's Zotero collections

### Benefits:
- Leverages user's existing research organization
- Respects user's curation and tagging
- Reduces redundant searches for known papers
- Maintains user's preferred bibliography format
- Enables collaborative research through shared Zotero groups

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

## 14) Roadmap

- **Phase 0**: Config-driven MVP, file-based I/O, AirFlow orchestration, OA only, Markdown reports
- **Phase 1**: Enhanced parallelism + vector DB + CLI improvements
- **Phase 2**: Robust Methodology Critic & Comparator; public/private dual view; FastAPI endpoints
- **Phase 3**: Web UI + Zotero Web integration + groups, ACL model
- **Phase 4**: Advanced UI features + HTML export; PDF exporter

## 15) How to Run MVP (conceptual)

### Prerequisites
1. Python environment prepared; Ollama installed; target models pulled (e.g., Llama 3.1 8B)
2. AirFlow installed and configured
3. API keys (as applicable) configured in environment
4. Zotero library accessible (local SQLite or API credentials)

### Execution Process
1. **Create config file**: Define research topic, parameters, sources in YAML/JSON
2. **Submit job**: Use CLI tool to submit configuration to AirFlow
3. **Monitor execution**: Check AirFlow UI for job progress and logs
4. **Retrieve results**: Access generated reports and artifacts in output directory

### Example Config Structure
```yaml
job:
  name: "llm-edge-devices-review"
  topic: "LLMs for small, low-power devices"
  date_range: "2020-2024"
  sources: ["arxiv", "pubmed", "semantic_scholar"]
  zotero:
    library_path: "/path/to/zotero.sqlite"
  output:
    directory: "/path/to/results"
    formats: ["markdown", "json", "csv"]
```

## 16) Pending Decisions

- Compile and periodically update API rate limits/quotas by source (arXiv, PubMed, Semantic Scholar, CrossRef)
- **Retention policy**: TODO
- **Group/user ACL specifics**: TODO
- **Final report**: start with Markdown; add PDF exporter later

## 17) Investigator Summary in Reports

Report includes investigators and institutions derived from metadata

### Content:
- Top authors (with affiliations where available) and their paper counts
- Top institutions and counts; emerging investigators (single‑paper authors in period)
- **Optional**: citation influence (if available from APIs)

### Normalization
Harmonize author names and affiliations; merge institution aliases

## 18) Saved Job Config & Scheduled Refresh

Persist job templates to re‑run literature scans and rebuild reports

### Core Schema (conceptual)
- **jobs** (topic, filters, sources, owners)
- **schedules** (manual/cron)  
- **runs** (history with deltas)

### Behaviors:
- **On‑demand**: user triggers new run for a saved job
- **Scheduled**: cron‑style schedule runs at configured times
- **Delta detection**: compare last run timestamp; mark newly added DOIs

### Report Variants:
- Full regenerated report
- Delta appendix: newly added papers since last run

## 19) Notification System

### Channels
- **Email** (default), optional Slack/Teams

### Triggers
- After scheduled/on‑demand run; emphasize when new papers found

### Settings per Job
- Recipients, channels, minimum delta threshold

### Example
**Email subject**: `ResearchUpdate: New publications on {topic}`

## 20) API Endpoints (planned)

```http
POST /jobs                           # create job (topic, filters, sources, optional schedule)
GET  /jobs/{job_id}                  # fetch job definition
POST /jobs/{job_id}/run              # trigger on‑demand run
GET  /jobs/{job_id}/runs             # list historical runs
GET  /jobs/{job_id}/report           # latest public report
GET  /jobs/{job_id}/report/private   # owner/group enriched view
POST /jobs/{job_id}/schedule         # set/update schedule
POST /papers/{paper_id}/upload_pdf   # upload Non‑OA PDF for private processing
```

## 21) Data Model Extensions

- **authors**: `id`, `name_norm`, `affiliation_norm`
- **paper_authors** (many‑to‑many): `paper_id`, `author_id`, `position`
- **institutions** (optional): `id`, `name_norm`, `aliases`
- **investigator_stats** (materialized/view): `author_id`, `papers_count`, `last_year_count`
- **reports**: add `investigator_summary_path` and visibility markers

## 22) Scheduling & Execution Notes

### MVP Scheduler (Phase 0)
- **AirFlow DAGs**: Each research job becomes an AirFlow DAG
- **File-based triggers**: Monitor config directories for new job files
- **Manual execution**: CLI commands to trigger individual jobs

### Production Scheduler
- **AirFlow workflows**: Full production DAGs with complex dependencies
- **Scheduled runs**: Cron-style scheduling for recurring literature reviews
- **Backoff & rate limits**: Honor API quotas; stagger queries; cache by DOI
- **Idempotency**: Dedupe by DOI + fuzzy title; safe re‑runs without duplication

### Job Management
- **Config versioning**: Track configuration file changes
- **Result archiving**: Maintain historical outputs and reports
- **Error handling**: Robust retry mechanisms and failure notifications

## 23) Security & Privacy

- **Notifications**: store minimal PII; encrypt API keys; restrict access tokens to job owners
- **Non‑OA PDFs**: private storage with owner/group ACL; file checksums; no redistribution
- **Audit trail**: per‑run logs (who/what/when), processing provenance

## 24) API Rate Limits & Throttling (documented policies)

### arXiv
- Public REST/ATOM; conservative throttle ~1 req/s; paginate; cache queries; jitter

### PubMed (NCBI E‑utilities)
- ~1 req/s baseline (higher with API key); include tool/email; honor Retry‑After; chain ESearch → EFetch

### Semantic Scholar
- REST; API key often required; ~1 req/s baseline; request only required fields; cache by DOI/paperId

### CrossRef REST
- Polite pool with mailto; ~1 req/s; include mailto in User‑Agent; filter by date/type; cache

### General Backoff Policy
- Exponential backoff with jitter on HTTP 429/503; centralized token‑bucket per source; configurable rps/burst/retries/timeouts/cache_ttl

### Telemetry
- Track request rates, 2xx/4xx/5xx, 429s, retries; alert on sustained throttling or high error rates

## 25) References

- Zotero Web API documentation (for future team setups)
- NCBI E‑utilities (PubMed), arXiv API, CrossRef REST API, Semantic Scholar API (for operational policies)

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