# ADR-001: Enhanced Pipeline Architecture for Research Library Assistance

**Date:** 2025-09-15 (Updated: 2025-09-17)  
**Author:** CServinL  
**Status:** Evolved

## Context

The Prisma Research Library Assistant needs a sophisticated architecture that automates research library management: discover, organize, analyze, and maintain research collections. The architecture has evolved from a simple document processing pipeline to a comprehensive research assistance system that includes Zotero integration, research streams, and intelligent library curation.

## Decision Evolution

**Original Decision (Phase 0)**: Simple document processing pipeline  
**Current Architecture**: Enhanced research library management system with persistent monitoring and intelligent organization

### Current Architecture
```
CLI → Research Stream Manager → Source Discovery (External APIs + Zotero Libraries) → Zotero Organization → AI Analysis → Research Insights
```

### Research Library Assistant Workflow

1. **Multi-Source Discovery**: External APIs + existing Zotero library search
2. **Relevance Assessment**: AI-based evaluation of research relevance to topics  
3. **Intelligent Curation**: Filter and organize relevant research automatically
4. **Duplicate Management**: Prevent redundant papers across research collections
5. **Content Analysis**: AI-powered insights and summaries for researchers
6. **Research Organization**: Structured collections, tags, and metadata management

## Data Flow (Current)
```
Research Stream Config → Research Assistant → 
  1. Multi-Source Discovery (External APIs + Zotero) → 
  2. Relevance Assessment (AI) → 
  3. Library Curation (Organize relevant research) → 
  4. Duplicate Management (Zotero integration) → 
  5. Content Analysis (AI insights) → 
  6. Research Organization → Enhanced Research Library + Insights
```

## Core Components (Updated)

### 1. Research Stream Manager (Core)
- **Responsibility**: Persistent research topic monitoring and library management
- **Functions**: Stream lifecycle, topic organization, collection management
- **Implementation**: Service layer for long-term research library curation

### 2. Research Discovery Engine
- **Responsibility**: Intelligent research discovery across multiple sources
- **Functions**: External API queries, Zotero library mining, result normalization
- **Implementation**: Zotero serves dual role as source AND organization backend

### 3. AI Research Assistant
- **Responsibility**: Intelligent research evaluation and content analysis
- **Functions**: Relevance assessment, research insights, cross-document analysis
- **Implementation**: Two-phase AI processing (quick curation + deep analysis)

### 4. Library Organization System
- **Responsibility**: Research collection management and organization
- **Functions**: Collection structuring, tagging, metadata management
- **Implementation**: Zotero-based organization with smart categorization

### 5. Research Insights Generator
- **Responsibility**: Research summaries and analytical insights
- **Functions**: Topic summaries, author analysis, research trend identification
- **Implementation**: AI-powered research assistance and knowledge extraction

## Key Architectural Evolution

### Research Library Focus
- **Persistent Research**: Research streams enable continuous library building vs one-time document processing
- **Zotero Collections**: Each research topic maps to organized library collections
- **Smart Organization**: Leverages Collections + Tags for research categorization

### Dual Zotero Role in Research Management
- **Source Integration**: Mine existing Zotero libraries for relevant research
- **Organization Backend**: Structure and organize research collections systematically
- **Offline Research**: Local HTTP API for library access, Web API for expansion

### AI-Powered Research Assistance
- **Research Curation**: AI evaluation of research relevance and quality
- **Content Organization**: Automatic categorization and organization of research
- **Knowledge Extraction**: AI insights and summaries for research comprehension
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
