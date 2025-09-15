# ADR-001: Simple Pipeline Architecture for Literature Review Automation

**Date:** 2025-09-15  
**Author:** CServinL

## Context

The Prisma AI-driven literature review system needs a straightforward architecture that automates the core literature review process: search, analyze, and report. The architecture should be simple to understand, implement, and maintain while providing the essential functionality for academic researchers.

## Decision

We will implement a **simple pipeline architecture** with four core components that work together in a linear workflow. This approach prioritizes simplicity and maintainability over complex orchestration.

### Architectural Rationale
- **Simplicity First**: Direct function calls between components, no complex messaging
- **Linear Pipeline**: Clear sequential flow from search to analysis to reporting
- **Component Specialization**: Each component has a single, well-defined responsibility
- **Academic Focus**: Designed specifically for literature review workflows
- **Local-First**: Self-contained system with minimal external dependencies

## Core Architecture Components

### 1. Coordinator
- **Responsibility**: Orchestrates the entire workflow
- **Functions**: Job management, error handling, progress tracking
- **Implementation**: Simple Python class with direct method calls

### 2. Search Agent
- **Responsibility**: Literature discovery and content acquisition
- **Functions**: Zotero integration, external API queries, PDF processing, deduplication
- **Implementation**: Unified component handling all search-related tasks

### 3. Analysis Agent
- **Responsibility**: Paper analysis and synthesis
- **Functions**: LLM-based summarization, thematic classification, comparison analysis
- **Implementation**: LLM integration for structured analysis tasks

### 4. Report Agent
- **Responsibility**: Output generation
- **Functions**: Markdown report generation, data export (CSV/JSON)
- **Implementation**: Template-based report generation

## Data Flow
```
Config File → Coordinator → Search Agent → Analysis Agent → Report Agent → Results
```

## Implementation Plan
- **Phase 0**: Basic pipeline with essential functionality
- **Phase 1**: Enhanced analysis and output options
- **Phase 2**: Optional collaborative features

## Benefits
- **Easy to Understand**: Simple linear flow that maps to research workflow
- **Quick to Implement**: Minimal complexity means faster development
- **Easy to Debug**: Clear component boundaries and data flow
- **Maintainable**: Simple architecture reduces maintenance overhead
- **Testable**: Each component can be tested independently

## Trade-offs
- **Limited Parallelism**: Sequential processing may be slower than parallel approaches
- **Less Flexibility**: Simpler than complex agent orchestration systems
- **Scalability Limits**: May need rework for very large-scale processing

## References
- Inspired by Unix pipeline philosophy: simple components working together
- Academic literature review best practices and workflows
## Consequences

### Positive
- ✅ **Quick Development**: Simple architecture enables rapid implementation
- ✅ **Easy to Understand**: Linear flow matches researcher mental models
- ✅ **Low Maintenance**: Fewer moving parts means less complexity
- ✅ **Reliable**: Simpler systems have fewer failure points
- ✅ **Academic Focus**: Designed specifically for literature review workflows

### Negative
- ⚠️ **Limited Parallelism**: Sequential processing may be slower for large datasets
- ⚠️ **Less Flexible**: Not as adaptable as complex agent systems

### Neutral
- 📝 **Scalability**: Can be enhanced in future phases if needed
- 📝 **Extensibility**: New features can be added to existing components

## Implementation Plan

### Phase 0: Core Pipeline
1. Implement the four core components
2. Basic configuration file parsing
3. Simple CLI interface
4. SQLite for job state storage

### Phase 1: Enhanced Features
1. Better analysis capabilities
2. Multiple output formats
3. Improved error handling

### Phase 2: Collaborative Features  
1. Web interface for report viewing
2. Shared configurations
3. Optional advanced orchestration

For detailed folder structure, see [ADR-006: Multi-Phase Project Folder Structure](./ADR-006-folder-structure.md).

For detailed folder structure, see [ADR-006: Multi-Phase Project Folder Structure](./ADR-006-folder-structure.md).

## Benefits of Multi-Agent Approach

### Maintained Clean Architecture Principles
- ✅ **Dependency Inversion**: Application depends on abstractions (`ResearchAgent`)
- ✅ **Testability**: Easy mocking through dependency injection
- ✅ **Separation of Concerns**: Infrastructure isolated from application logic
- ✅ **Extensibility**: New agent types integrate seamlessly

### Optimized for Simplicity
- ✅ **Declarative Code**: Service methods are clear and readable
- ✅ **Minimal Overhead**: No unnecessary abstraction layers
- ✅ **Configuration-Driven**: Agent assembly through YAML and DI
- ✅ **Appropriate Complexity**: Architecture matches business requirements

## References
- [Hexagonal Architecture (Ports and Adapters) by Alistair Cockburn](https://alistair.cockburn.us/hexagonal-architecture/)
- [Clean Architecture by Robert C. Martin](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
