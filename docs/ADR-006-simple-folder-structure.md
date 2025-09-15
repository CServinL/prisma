# ADR-006: Simple Project Folder Structure

**Date:** 2025-09-14  
**Author:** CServinL

## Context

The Prisma literature review system needs a clear folder structure that:
- Organizes our 4 main components (Coordinator, Search Agent, Analysis Agent, Report Agent)
- Keeps things simple for small team development
- Allows easy testing and maintenance
- Follows Python best practices

## Decision

Use a **simple functional structure** based on our 4-component pipeline.

## Structure

```
prisma/
├── README.md
├── LICENSE
├── requirements.txt
├── config/
│   └── default.yaml              # Default configuration
├── src/
│   ├── __init__.py
│   ├── coordinator.py            # Main pipeline coordinator
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── search_agent.py       # Paper search logic
│   │   ├── analysis_agent.py     # Paper analysis/summarization  
│   │   └── report_agent.py       # Final report generation
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   └── ollama_client.py  # Ollama integration
│   │   └── search/
│   │       ├── pubmed.py         # PubMed API
│   │       └── arxiv.py          # ArXiv API
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py           # SQLite operations
│   │   └── models.py             # Data models
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py               # Typer CLI application
│   └── utils/
│       ├── __init__.py
│       ├── config.py             # Configuration loading
│       └── logging.py            # Logging setup
├── tests/
│   ├── __init__.py
│   ├── test_coordinator.py
│   ├── test_agents/
│   │   ├── test_search_agent.py
│   │   ├── test_analysis_agent.py
│   │   └── test_report_agent.py
│   ├── test_integrations/
│   └── test_storage/
├── docs/
│   ├── *.md                      # ADR files and guides
│   └── *.drawio                  # Diagrams
└── scripts/
    └── setup_structure.py       # Development helpers
```

## Key Principles

### Simple Organization
- **One folder per component**: Easy to find code for each agent
- **Clear separation**: Integrations separate from core logic
- **Standard Python layout**: Following common Python project patterns
- **Test mirroring**: Test structure matches source structure

### Functional Areas
- `src/agents/`: Our 4 main processing components
- `src/integrations/`: External service connections (LLM, search APIs)
- `src/storage/`: Database and data models
- `src/cli/`: Command-line interface
- `src/utils/`: Shared utilities and configuration

### Development Benefits
- **Easy navigation**: Find any component quickly
- **Clear dependencies**: Integration layer isolates external services
- **Simple testing**: One test file per source file
- **Easy maintenance**: Small, focused modules

## Benefits

- **Simple**: Easy to understand for new developers
- **Focused**: Structure matches our 4-component architecture
- **Maintainable**: Clear separation makes changes easier
- **Testable**: Test structure mirrors code structure
- **Extensible**: Easy to add new integrations or utilities

## When to Reorganize

Only if we:
- Add significantly more components (>8-10)
- Need multiple deployment configurations
- Add web interface requiring separate frontend
- Scale to multiple teams working in parallel

For now, this simple structure serves our MVP needs perfectly.

---

**Related ADRs**: 
- [ADR-001: Simple Pipeline Architecture](./ADR-001-simple-pipeline-architecture.md)
- [ADR-004: Simple CLI Interface](./ADR-004-simple-cli-interface.md)
├── FOLDER_STRUCTURE.md
├── .gitignore
├── pyproject.toml                    # Python project configuration
├── requirements/                     # Phase-specific dependencies
│   ├── base.txt                     # Core dependencies (Phase 0+)
│   ├── api.txt                      # API dependencies (Phase 1+)
│   ├── web.txt                      # Web dependencies (Phase 2+)
│   └── enterprise.txt               # Enterprise dependencies (Phase 3+)
│
├── src/                             # Main source code
│   ├── __init__.py
│   ├── core/                        # Core domain logic (Phase 0)
│   │   ├── __init__.py
│   │   ├── models/                  # Domain models and entities
│   │   │   ├── __init__.py
│   │   │   ├── research_job.py
│   │   │   ├── paper.py
│   │   │   ├── query.py
│   │   │   └── workflow.py
│   │   ├── workflows/               # Workflow orchestration
│   │   │   ├── __init__.py
│   │   │   ├── literature_review.py
│   │   │   ├── coordinator.py
│   │   │   └── pipeline.py
│   │   └── services/                # Core business services
│   │       ├── __init__.py
│   │       ├── job_manager.py
│   │       ├── result_aggregator.py
│   │       └── progress_tracker.py
│   │
│   ├── agents/                      # AI Agent implementations
│   │   ├── __init__.py
│   │   ├── base/                    # Base agent classes (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── message_handler.py
│   │   │   └── task_executor.py
│   │   ├── search/                  # Search agents (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── pubmed_agent.py
│   │   │   ├── arxiv_agent.py
│   │   │   └── ieee_agent.py
│   │   ├── processing/              # Processing agents (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── abstract_extractor.py
│   │   │   ├── metadata_parser.py
│   │   │   └── content_analyzer.py
│   │   ├── synthesis/               # Synthesis agents (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── summary_generator.py
│   │   │   ├── report_compiler.py
│   │   │   └── citation_formatter.py
│   │   ├── specialized/             # Specialized agents (Phase 1)
│   │   │   ├── __init__.py
│   │   │   ├── quality_assessor.py
│   │   │   ├── trend_analyzer.py
│   │   │   └── bias_detector.py
│   │   └── advanced/                # Advanced agents (Phase 2+)
│   │       ├── __init__.py
│   │       ├── ml_researcher.py
│   │       ├── domain_expert.py
│   │       └── collaboration_agent.py
│   │
│   ├── orchestrator/                # Agent coordination (Phase 0)
│   │   ├── __init__.py
│   │   ├── coordinator.py
│   │   ├── message_passing.py
│   │   ├── job_scheduler.py
│   │   └── resource_manager.py
│   │
│   ├── integrations/                # External service integrations
│   │   ├── __init__.py
│   │   ├── external_apis/           # External APIs (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── pubmed_client.py
│   │   │   ├── arxiv_client.py
│   │   │   └── ieee_client.py
│   │   ├── llm/                     # LLM integrations (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── openai_client.py
│   │   │   ├── anthropic_client.py
│   │   │   └── local_llm_client.py
│   │   ├── vector_db/               # Vector database (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── chromadb_client.py
│   │   │   ├── pinecone_client.py
│   │   │   └── weaviate_client.py
│   │   ├── zotero/                  # Reference manager (Phase 1)
│   │   │   ├── __init__.py
│   │   │   ├── zotero_client.py
│   │   │   └── mendeley_client.py
│   │   └── cloud/                   # Cloud services (Phase 3)
│   │       ├── __init__.py
│   │       ├── aws_services.py
│   │       ├── azure_services.py
│   │       └── gcp_services.py
│   │
│   ├── storage/                     # Data persistence (Phase 0)
│   │   ├── __init__.py
│   │   ├── repositories/            # Data access layer
│   │   │   ├── __init__.py
│   │   │   ├── job_repository.py
│   │   │   ├── paper_repository.py
│   │   │   └── result_repository.py
│   │   ├── models/                  # Database models
│   │   │   ├── __init__.py
│   │   │   ├── database.py
│   │   │   └── migrations/
│   │   └── cache/                   # Caching layer
│   │       ├── __init__.py
│   │       ├── redis_cache.py
│   │       └── memory_cache.py
│   │
│   ├── interfaces/                  # User interfaces
│   │   ├── __init__.py
│   │   ├── cli/                     # Command line interface (Phase 0)
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── commands/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── review.py
│   │   │   │   ├── config.py
│   │   │   │   └── monitor.py
│   │   │   ├── validation.py
│   │   │   └── formatters.py
│   │   ├── api/                     # REST API (Phase 1)
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── routers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── jobs.py
│   │   │   │   ├── papers.py
│   │   │   │   ├── auth.py
│   │   │   │   └── admin.py
│   │   │   ├── middleware/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py
│   │   │   │   ├── cors.py
│   │   │   │   └── rate_limit.py
│   │   │   └── schemas/
│   │   │       ├── __init__.py
│   │   │       ├── job_schemas.py
│   │   │       ├── paper_schemas.py
│   │   │       └── user_schemas.py
│   │   └── web/                     # Web UI (Phase 2)
│   │       ├── __init__.py
│   │       ├── frontend/            # React application
│   │       │   ├── public/
│   │       │   ├── src/
│   │       │   │   ├── components/
│   │       │   │   ├── pages/
│   │       │   │   ├── hooks/
│   │       │   │   ├── services/
│   │       │   │   └── utils/
│   │       │   ├── package.json
│   │       │   └── README.md
│   │       └── templates/           # Server-side templates (if needed)
│   │
│   ├── utils/                       # Utility functions (Phase 0)
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   ├── config.py
│   │   ├── validators.py
│   │   ├── formatters.py
│   │   └── helpers.py
│   │
│   ├── auth/                        # Authentication & Authorization (Phase 1)
│   │   ├── __init__.py
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── jwt_provider.py
│   │   │   ├── oauth_provider.py
│   │   │   └── ldap_provider.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── role.py
│   │   │   └── permission.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── auth_service.py
│   │       └── user_service.py
│   │
│   ├── analytics/                   # Analytics & Reporting (Phase 2)
│   │   ├── __init__.py
│   │   ├── collectors/
│   │   │   ├── __init__.py
│   │   │   ├── usage_collector.py
│   │   │   └── performance_collector.py
│   │   ├── processors/
│   │   │   ├── __init__.py
│   │   │   ├── trend_processor.py
│   │   │   └── insight_processor.py
│   │   └── exporters/
│   │       ├── __init__.py
│   │       ├── dashboard_exporter.py
│   │       └── report_exporter.py
│   │
│   └── enterprise/                  # Enterprise features (Phase 3)
│       ├── __init__.py
│       ├── compliance/
│       │   ├── __init__.py
│       │   ├── audit_logger.py
│       │   └── data_governance.py
│       ├── scaling/
│       │   ├── __init__.py
│       │   ├── load_balancer.py
│       │   └── cluster_manager.py
│       └── monitoring/
│           ├── __init__.py
│           ├── health_checker.py
│           └── metrics_collector.py
│
├── config/                          # Configuration files (Phase 0)
│   ├── default.yaml
│   ├── development.yaml
│   ├── production.yaml
│   ├── testing.yaml
│   └── schemas/
│       ├── job_config_schema.yaml
│       └── agent_config_schema.yaml
│
├── tests/                           # Test suite
│   ├── __init__.py
│   ├── unit/                        # Unit tests (Phase 0)
│   │   ├── __init__.py
│   │   ├── core/
│   │   ├── agents/
│   │   ├── orchestrator/
│   │   └── utils/
│   ├── integration/                 # Integration tests (Phase 0)
│   │   ├── __init__.py
│   │   ├── workflows/
│   │   ├── api/
│   │   └── storage/
│   ├── e2e/                        # End-to-end tests (Phase 1)
│   │   ├── __init__.py
│   │   ├── cli/
│   │   ├── api/
│   │   └── web/
│   ├── performance/                 # Performance tests (Phase 2)
│   │   ├── __init__.py
│   │   ├── load_tests/
│   │   └── benchmarks/
│   ├── fixtures/                    # Test data and fixtures
│   │   ├── sample_papers/
│   │   ├── mock_responses/
│   │   └── test_configs/
│   └── conftest.py
│
├── docs/                           # Documentation
│   ├── README.md
│   ├── ADR-001-multi-agent-architecture.md
│   ├── ADR-002-research-documentation-standards.md
│   ├── ADR-003-agent-service-injection.md
│   ├── ADR-004-cli-workflow-interface.md
│   ├── ADR-005-async-agent-communication.md
│   ├── user-guide/                  # User documentation
│   │   ├── getting-started.md
│   │   ├── cli-reference.md
│   │   ├── api-reference.md         # Phase 1
│   │   └── web-interface.md         # Phase 2
│   ├── developer-guide/             # Developer documentation
│   │   ├── architecture.md
│   │   ├── agent-development.md
│   │   ├── contributing.md
│   │   └── deployment.md
│   ├── api/                        # API documentation (Phase 1)
│   │   ├── openapi.yaml
│   │   └── postman_collection.json
│   └── deployment/                  # Deployment guides
│       ├── docker.md
│       ├── kubernetes.md            # Phase 2
│       └── cloud-deployment.md      # Phase 3
│
├── scripts/                        # Utility scripts
│   ├── setup.py                    # Environment setup
│   ├── build.py                    # Build automation
│   ├── deploy.py                   # Deployment scripts
│   ├── data_migration.py           # Data migration
│   └── performance_profiling.py    # Performance analysis
│
├── deployment/                     # Deployment configurations
│   ├── docker/
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml
│   │   └── docker-compose.prod.yml
│   ├── kubernetes/                 # Phase 2
│   │   ├── namespace.yaml
│   │   ├── deployments/
│   │   ├── services/
│   │   └── ingress/
│   ├── terraform/                  # Phase 3
│   │   ├── modules/
│   │   └── environments/
│   └── ansible/                    # Phase 3
│       ├── playbooks/
│       └── roles/
│
├── examples/                       # Usage examples
│   ├── basic_review/
│   │   ├── config.yaml
│   │   ├── run.py
│   │   └── README.md
│   ├── advanced_workflows/         # Phase 1
│   │   ├── multi_database_search/
│   │   ├── custom_analysis/
│   │   └── collaborative_review/
│   └── enterprise_scenarios/       # Phase 3
│       ├── large_scale_analysis/
│       └── compliance_reporting/
│
├── data/                          # Data directory (gitignored)
│   ├── cache/
│   ├── jobs/
│   ├── results/
│   ├── logs/
│   └── temp/
│
└── .github/                       # GitHub workflows and templates
    ├── workflows/
    │   ├── ci.yml
    │   ├── cd.yml
    │   ├── security.yml
    │   └── release.yml
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   ├── feature_request.md
    │   └── research_request.md
    └── PULL_REQUEST_TEMPLATE.md
```

## Phase-by-Phase Implementation Guide

### Phase 0: CLI + Core Engine
**Focus**: Basic functionality, CLI interface, core agents
**Folders to implement**:
- `src/core/`
- `src/agents/base/`, `src/agents/search/`, `src/agents/processing/`, `src/agents/synthesis/`
- `src/orchestrator/`
- `src/interfaces/cli/`
- `src/integrations/external_apis/`, `src/integrations/llm/`, `src/integrations/vector_db/`
- `src/storage/repositories/`
- `src/utils/`
- `config/`
- `tests/unit/`, `tests/integration/`

### Phase 1: API + Enhanced Features
**Focus**: REST API, advanced agents, external integrations
**Additional folders**:
- `src/interfaces/api/`
- `src/agents/specialized/`
- `src/integrations/zotero/`
- `src/auth/`
- `tests/e2e/`

### Phase 2: Web UI + Collaboration
**Focus**: Web interface, user management, collaboration
**Additional folders**:
- `src/interfaces/web/`
- `src/agents/advanced/`
- `src/analytics/`
- `tests/performance/`

### Phase 3: Enterprise + Analytics
**Focus**: Enterprise features, analytics, advanced deployment
**Additional folders**:
- `src/enterprise/`
- `src/integrations/cloud/`
- `deployment/kubernetes/`, `deployment/terraform/`, `deployment/ansible/`

## Consequences

### Positive Consequences:
- **No future reorganization**: Structure supports growth from CLI to enterprise platform
- **Parallel development**: Teams can work independently on different phases
- **Clear boundaries**: Each phase has well-defined scope and deliverables
- **Intuitive navigation**: Consistent naming and organization across all phases
- **Modular architecture**: Components can be developed and tested independently
- **Enterprise ready**: Structure anticipates advanced features and deployment needs

### Trade-offs Accepted:
- **Initial complexity**: More directories upfront than minimal Phase 0 structure
- **Empty directories**: Some Phase 2/3 directories remain empty during early development
- **Learning curve**: Developers need to understand multi-phase organization

### Risks and Mitigations:
- **Over-engineering early phases**: *Mitigation*: Focus development on Phase 0 directories first
- **Directory sprawl**: *Mitigation*: Clear documentation of what belongs in each directory
- **Inconsistent usage**: *Mitigation*: Code review guidelines and automated linting for imports