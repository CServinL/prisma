# ADR-007: Research Streams Architecture for Intelligent Library Management

**Date:** 2025-09-15  
**Author:** CServinL  
**Status:** Accepted

## Context

Research library management is typically a manual, time-intensive activity, but researchers need **continuous, intelligent organization** of their research collections. The traditional approach requires manual searches and lacks intelligent curation. Researchers need a Research Library Assistant that can:

- Create persistent research topics that automatically discover and organize relevant research
- Intelligently curate research collections using existing tools (Zotero) without disruption  
- Leverage both Collections and Tags for smart research organization
- Maintain continuous awareness and organization of evolving research areas

## Decision

We will implement **Research Streams** - an intelligent research library management architecture that leverages Zotero Collections and smart tagging for continuous research discovery and organization.

### Core Concept
```
Research Stream = Zotero Collection + Research Criteria + Smart Tags + AI Curation + Auto-Monitoring
```

### Research Library Management Principles

1. **Persistent Research Organization**: Research topics persist and evolve beyond single discovery sessions
2. **Intelligent Automation**: Streams automatically discover and curate relevant research on schedule
3. **Smart Organization**: Leverage Zotero's Collections + Tags for intelligent research categorization
4. **Non-disruptive Integration**: Works within existing research workflows and library infrastructure
5. **AI-Powered Curation**: Smart research assessment and organization based on content analysis

## Research Streams Components

### 1. Stream Definition
```python
ResearchStream(
    id="neural-networks-2024",
    name="Neural Networks 2024", 
    search_criteria=SearchCriteria(
        query="neural networks transformer attention",
        max_results=100
    ),
    collection_name="Prisma: Neural Networks 2024",
    refresh_frequency=RefreshFrequency.WEEKLY,
    smart_tags=[...] 
)
```

### 2. Smart Collections + Tags Strategy

**📁 Collections = Research Topics**
- Hierarchical organization by research area
- Examples: `Neural Networks/Transformers`, `AI Ethics`, `Quantum ML`
- Each stream maps to a dedicated Zotero collection

**🏷️ Tags = Cross-cutting Metadata**
- **Prisma Tags**: `prisma-[stream-id]`, `prisma-auto`
- **Temporal Tags**: `year-2024`, `recent`, `foundational`
- **Methodology Tags**: `survey`, `empirical`, `theoretical`  
- **Status Tags**: `to-read`, `key-paper`, `cited-in-report`
- **Quality Tags**: `high-impact`, `peer-reviewed`

### 3. Automated Library Management Workflow
1. **Stream Creation**: User defines research topic and criteria
2. **Initial Population**: Discover and organize relevant research into collections
3. **Continuous Monitoring**: Scheduled discovery for new research content
4. **Smart Organization**: Automatic categorization based on content analysis
5. **Deduplication**: Prevent redundant research across streams
6. **Library Enhancement**: Generate insights and organization improvements from stream contents

## Benefits

### For Researchers
- **Continuous Organization**: Research library stays updated automatically
- **Intelligent Discovery**: Research automatically sorted into collections
- **Cross-topic Analysis**: Tags enable queries across multiple research areas
- **Reduced Manual Work**: Automated discovery and organization

### For Research Library Assistant System
- **Persistent Research Topics**: Research areas become long-lived, managed entities
- **Better Organization**: Collections + Tags provide flexible research management
- **Incremental Updates**: Only process new research, not entire library
- **User Engagement**: Researchers interact with system for ongoing library management

## Implementation

### Data Models
- `ResearchStream`: Core stream definition and metadata
- `SearchCriteria`: Configurable search parameters
- `SmartTag`: Categorized tags with auto-generation rules
- `StreamUpdateResult`: Update outcomes and statistics

### Service Layer
- `ResearchStreamManager`: Core service for stream lifecycle
- Integration with existing Zotero clients for collection management
- Automated scheduling and update coordination

### CLI Interface
```bash
prisma streams create "Neural Networks 2024" "neural networks transformer"
prisma streams list --status active
prisma streams update --all
prisma streams info neural-networks-2024
```

## Alternatives Considered

### 1. **One-time Research Discovery Only**
- **Rejected**: Doesn't meet researcher needs for continuous library management
- **Problem**: Researchers lose track of new developments in their research areas

### 2. **External Research Management Systems**
- **Rejected**: Adds complexity and doesn't integrate with existing tools
- **Problem**: Creates tool fragmentation and workflow disruption

### 3. **Manual Zotero Collections**
- **Rejected**: Lacks automation and intelligent organization
- **Problem**: Still requires manual discovery and categorization

## Consequences

### Positive
- **Enhanced User Value**: Continuous library management vs. one-time discovery
- **Better Organization**: Structured approach to research topic management
- **Zotero Integration**: Leverages existing user workflows and research libraries
- **Scalable**: Can handle many streams with automated processing

### Negative
- **Increased Complexity**: More sophisticated data models and workflows
- **Storage Requirements**: Persistent stream state and scheduling
- **Dependency on Zotero**: Requires Zotero for full functionality

## Status

**Accepted** - Implemented in Day 2 development with full CLI interface and service layer.

## Related ADRs
- ADR-001: Simple Pipeline Architecture (streams integrate with existing pipeline)
- ADR-008: Enhanced Zotero Integration (streams leverage advanced Zotero capabilities)