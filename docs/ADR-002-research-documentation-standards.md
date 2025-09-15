# ADR-002: Documentation Standards for AI Research Systems

**Date:** 2025-09-14  
**Author:** CServinL

## Context
The Prisma AI-driven literature review system requires comprehensive documentation to:
- **Support academic rigor**: Clear documentation for research reproducibility and peer review
- **Enable AI agent coordination**: Well-documented interfaces for agent-to-agent communication
- **Facilitate research validation**: Structured documentation for methodology verification
- **Ensure academic integrity**: Comprehensive audit trails and provenance documentation
- **Support open science**: Clear documentation for community contribution and transparency

Modern AI research systems emphasize machine-readable documentation that serves researchers, AI agents, and academic review processes.

## Decision

### Documentation Strategy
We will implement a **research-focused documentation approach**:

1. **Architectural Documentation** - ADRs for major system decisions
2. **API Documentation** - Auto-generated from agent interfaces
3. **Research Documentation** - Methodology, algorithms, and validation
4. **Academic Documentation** - Citation standards, ethical guidelines, reproducibility

### Docstring Standard: Research-Focused Python Documentation

#### **Choice: Google Style with Academic Extensions**
We will use **Google-style docstrings** enhanced with academic research metadata:

```python
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

class LiteratureAgent(ABC):
    """Abstract base class for literature review agents in systematic review workflows.
    
    This interface provides a unified abstraction for specialized agents that process
    academic literature, following systematic review methodologies (PRISMA guidelines)
    where each agent performs specific, auditable operations on research papers.
    
    Academic Context:
        Based on systematic review methodologies including:
        - PRISMA (Preferred Reporting Items for Systematic Reviews and Meta-Analyses)
        - Cochrane Handbook for Systematic Reviews
        - Campbell Collaboration guidelines
    
    Examples:
        Basic agent implementation:
        
        >>> class CitationExtractionAgent(LiteratureAgent):
        ...     @property
        ...     def agent_id(self) -> str:
        ...         return "citation_extractor_v1"
        ...     
        ...     async def process(self, papers: List[Paper]) -> ProcessingResult:
        ...         return ProcessingResult(
        ...             processed_papers=papers,
        ...             metadata={"citations_extracted": 150}
        ...         )
    
    Attributes:
        agent_id: Unique identifier for the agent (used in provenance tracking)
        version: Agent version for reproducibility
        capabilities: List of operations this agent can perform
        
    Note:
        All agents must maintain audit trails for academic integrity.
        Processing results must include provenance metadata.
    """
        
        Usage in research context:
        
        >>> agent = LiteratureSearchAgent()
        >>> results = await agent.execute_search()
        >>> print(results["status"])  # "completed"
    
    Note:
        All I/O operations are async to support real network calls and
        maintain consistent interface regardless of agent type.
    """
    
    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique identifier for this research agent.
        
        Returns:
            Unique string identifier used for agent registration and provenance tracking.
            Should be immutable throughout agent lifecycle.
            
        Note:
            Format convention: {type}_{version}_{sequence} (e.g., "pubmed_v1_01", "llm_synthesis_v2")
        """
        
    @abstractmethod
    async def process(self, input_data: Any) -> ProcessingResult:
        """Process research data according to agent specialization.
        
        Args:
            input_data: Research data to process. Type depends on agent implementation:
                - Search agents: query parameters and filters
                - Processing agents: list of papers or raw content
                - Synthesis agents: processed data and analysis requirements
        
        Returns:
            ProcessingResult containing:
                - processed_data: Agent-specific output
                - metadata: Processing statistics and provenance
                - audit_trail: Academic integrity and methodology records
            
        Raises:
            ConnectionError: When external APIs are unreachable
            ValidationError: When input data fails academic standards
            TimeoutError: When processing exceeds configured limits
            
        Examples:
            Search agent processing:
            >>> query = ResearchQuery("machine learning healthcare")
            >>> result = await pubmed_agent.process(query)
            >>> print(len(result.processed_data))  # 150 papers
            
            Processing agent analysis:
            >>> papers = [paper1, paper2, paper3]
            >>> result = await analysis_agent.process(papers)
            >>> print(result.metadata["abstracts_extracted"])  # 3
        """
        
    async def get_capabilities(self) -> List[str]:
        """Get list of research operations this agent can perform.
        
        Returns:
            List of capability strings describing agent functions:
            - Search agents: ["pubmed_search", "filter_by_date", "extract_metadata"]
            - Processing agents: ["pdf_extraction", "abstract_analysis", "citation_parsing"]
            - Synthesis agents: ["summary_generation", "gap_analysis", "recommendation_synthesis"]
            
        Examples:
            >>> capabilities = await agent.get_capabilities()
            >>> if "citation_parsing" in capabilities:
            ...     result = await agent.process(papers_with_citations)
        """

    async def get_status(self) -> Dict[str, Any]:
        """Get comprehensive agent status and diagnostic information.
        
        Provides agent health information and current processing state
        for workflow coordination and monitoring.
        
        Returns:
            Status dictionary containing:
            - agent_id: Agent identifier
            - agent_type: Agent classification string  
            - status: "ready" | "processing" | "error" | "offline"
            - current_task: Description of current processing (if active)
            - performance_metrics: Processing statistics
            - error_message: Error description (if applicable)
            
        Note:
            This method should never raise exceptions. Errors are captured
            in the status response for graceful workflow degradation.
            
        Examples:
            Ready agent:
            >>> status = await agent.get_status()
            >>> print(status)
            {
                "agent_id": "pubmed_v1_01",
                "agent_type": "search_agent", 
                "status": "ready",
                "performance_metrics": {
                    "papers_processed": 1205,
                    "avg_processing_time": 2.3
                }
            }
            
            Processing agent:
            >>> status = await busy_agent.get_status()
            >>> print(status["current_task"])  # "Processing 50 papers for systematic review"
        """
```

### Documentation Levels

#### **1. Interface/Port Documentation (Comprehensive)**
- **Purpose**: Contract definition and usage examples
- **Audience**: Other developers, AI assistants, API consumers
- **Include**: Examples, error cases, type information, usage patterns

#### **2. Domain Entity Documentation (Business-Focused)**
```python
class ResearchJob:
    """Research job aggregate managing literature review workflow execution.
    
    Represents a complete systematic literature review with specialized agents,
    research parameters, and quality controls. Enforces academic integrity rules
    around methodology validation, citation tracking, and reproducibility standards.
    
    Academic Integrity Rules:
        - Research parameters must be validated before workflow execution
        - All agent processing must maintain citation provenance
        - Paper identifiers (DOI, PMID) must be unique within a research job  
        - All research operations are tracked for reproducibility audits
        - Methodology compliance verified according to systematic review guidelines
    """
```

#### **3. Application Service Documentation (Use-Case Focused)**
```python
class WorkflowOrchestrator:
    """Application service for literature review workflow coordination.
    
    Orchestrates research operations for systematic literature review scenarios.
    Provides error handling, progress tracking, and academic integrity validation
    for research workflows.
    """
    
    async def execute_literature_search(self, query: ResearchQuery) -> Dict[str, Any]:
        """Execute literature search workflow use case.
        
        Args:
            query: Research query with parameters and filters
            
        Returns:
            Search operation result with paper count, sources, and quality metrics
            
        Academic Standards:
            - Follows PRISMA systematic review guidelines
            - Maintains search strategy documentation
            - Records inclusion/exclusion criteria application
        """
```

#### **4. Infrastructure Adapter Documentation (Implementation-Focused)**
```python
class PubMedSearchAdapter(ResearchAgent):
    """PubMed API adapter for biomedical literature search.
    
    Implements ResearchAgent interface by querying PubMed/MEDLINE database
    for relevant academic papers using E-utilities API.
    
    Configuration:
        - API_KEY: Optional NCBI API key for higher rate limits
        - EMAIL: Required contact email for API usage
        - TIMEOUT: Request timeout in seconds (default: 30)
        - MAX_RESULTS: Maximum papers per query (default: 10000)
    """
```

### Visual Documentation Standards

#### **Diagram Format: Draw.io**
All system diagrams will use **draw.io format** (.drawio files) for consistency and accessibility:

**Rationale:**
- ✅ **Cross-platform compatibility**: Works on Windows, Mac, Linux
- ✅ **Web-based editing**: No software installation required (app.diagrams.net)
- ✅ **VS Code integration**: Direct editing with Draw.io Integration extension
- ✅ **Version control friendly**: XML-based format works well with Git
- ✅ **Export flexibility**: SVG, PNG, PDF export for documentation embedding
- ✅ **Template library**: Rich set of software architecture templates

**Standard Diagram Types:**
- **Architecture Diagrams**: System components and interactions with swim lanes
- **Data Flow Diagrams**: Information flow between agents and services
- **Sequence Diagrams**: Agent coordination and message passing
- **Component Diagrams**: Module relationships and dependencies
- **Deployment Diagrams**: Infrastructure and scaling configurations

**Naming Convention:**
- File format: `{topic}-{type}.drawio` (e.g., `information-flow-diagram.drawio`)
- Export format: `{topic}-{type}.drawio.svg` for embedding in markdown
- Accompanied by: `{topic}-{type}.md` documentation explaining the diagram

**Editing Workflow:**
1. **Online Editing**: Open .drawio files at [app.diagrams.net](https://app.diagrams.net/)
2. **VS Code Editing**: Install [Draw.io Integration](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio) extension
3. **Export for Docs**: Save as SVG for embedding in markdown files
4. **Version Control**: Commit both .drawio source and .svg export files

**Diagram Standards:**
- Use **swim lanes** for agent-based architectures to show clear separation of concerns
- Include **flow direction indicators** (arrows) for data and control flow
- Use **consistent color coding** across diagrams (same colors for same component types)
- Add **sequence numbers** for complex workflows to show execution order
- Include **legend** explaining symbols, colors, and flow types

**Template Usage:**
```markdown
## System Architecture

![Architecture Diagram](diagram-name.drawio.svg)

**📝 Edit this diagram**: Open [diagram-name.drawio](diagram-name.drawio) in [draw.io](https://app.diagrams.net/)
```

#### **Academic Research Diagrams**
For research methodology and algorithm documentation:
- **Flowcharts**: Research workflow and decision points
- **Process Diagrams**: Literature review methodology (PRISMA flow)
- **Algorithm Visualizations**: Machine learning and analysis pipelines
- **Validation Frameworks**: Quality assurance and verification processes

### Documentation Tools

#### **Auto-Documentation Generation**
- **Sphinx** with autodoc for API documentation
- **Type hints** for parameter and return documentation
- **docstring-parser** for structured docstring validation

#### **Documentation Validation**
- **pydocstyle** for docstring quality checking
- **mypy** for type annotation validation
- **interrogate** for documentation coverage metrics

#### **IDE Integration**
- All docstrings compatible with VS Code, PyCharm IntelliSense
- Hover documentation shows examples and type information
- Auto-completion understands return types and exceptions

## Consequences

### Positive
- ✅ **AI-Friendly**: Structured docstrings help AI assistants understand code context
- ✅ **Self-Documenting**: Type hints + docstrings reduce separate documentation need
- ✅ **Tool Integration**: Modern IDEs provide rich code assistance
- ✅ **Consistency**: Clear standards for all team members
- ✅ **Maintainability**: Examples in docstrings serve as inline tests

### Negative
- ⚠️ **Initial Overhead**: More time spent writing documentation
- ⚠️ **Maintenance Cost**: Docstrings need updates when code changes
- ⚠️ **Verbosity**: Some simple methods become heavily documented

### Neutral
- 📝 **Learning Curve**: Team needs to adopt Google docstring style
- 📝 **Tool Setup**: Requires configuration of documentation tools

## Implementation Guidelines

### **Must Document**
- All public interfaces (ports, services)
- Domain entities and business rules
- Complex algorithms or business logic
- Error handling patterns

### **Should Document** 
- Public methods with non-obvious behavior
- Configuration and setup procedures
- Integration patterns

### **May Skip Documentation**
- Simple getters/setters with obvious behavior
- Private helper methods
- Trivial implementations

### **Documentation Checklist**
- [ ] Purpose clearly stated
- [ ] Parameters and return types documented
- [ ] Exceptions listed with conditions
- [ ] Usage examples provided (for interfaces)
- [ ] Business rules explained (for domain code)

## Development Methodology: Test-Driven Development (TDD)

### Decision
We will follow **Test-Driven Development (TDD)** practices for all core components:

1. **Write Tests First**: Always design and write tests before implementing functionality
2. **Red-Green-Refactor**: Follow the classic TDD cycle
3. **Test Documentation**: Tests serve as living documentation of expected behavior

### TDD Implementation Process

#### 1. Design Phase
- **Define interface**: What should the component do?
- **Write test cases**: Cover normal cases, edge cases, and error conditions
- **Document expected behavior**: Tests capture requirements clearly

#### 2. Implementation Phase
```bash
# TDD Cycle
1. Write failing test (RED)
2. Write minimal code to pass test (GREEN)  
3. Refactor and improve code (REFACTOR)
4. Repeat
```

#### 3. Component Testing Strategy
- **Unit Tests**: Individual agent functions and methods
- **Integration Tests**: Agent-to-agent communication
- **End-to-End Tests**: Complete pipeline workflows
- **Configuration Tests**: YAML config validation

### Benefits for Literature Review System
- **Academic Rigor**: Tests validate research methodology implementation
- **Reliability**: Critical for academic research - results must be reproducible
- **Refactoring Safety**: Allows architecture improvements without breaking functionality
- **Documentation**: Tests show exactly how components should behave
- **Quality Assurance**: Prevents bugs in research analysis pipeline

### Testing Structure
```
tests/
├── unit/
│   ├── test_search_agent.py      # Search functionality
│   ├── test_analysis_agent.py    # LLM analysis  
│   └── test_report_agent.py      # Report generation
├── integration/
│   ├── test_pipeline.py          # End-to-end workflows
│   └── test_coordinator.py       # Component coordination
└── fixtures/
    ├── sample_papers.json        # Test data
    └── config_examples/          # Test configurations
```

### Test Requirements
- **Coverage**: Minimum 80% code coverage for core components
- **Isolation**: Tests must not depend on external APIs in CI/CD
- **Speed**: Unit tests complete in <10 seconds total
- **Clarity**: Test names clearly describe what is being tested

*Rationale: Academic research demands high reliability and reproducibility. TDD ensures our literature review pipeline produces consistent, trustworthy results that researchers can depend on for their work.*

## References
- [Google Python Style Guide - Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [PEP 257 - Docstring Conventions](https://peps.python.org/pep-0257/)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [Sphinx Documentation](https://www.sphinx-doc.org/)
