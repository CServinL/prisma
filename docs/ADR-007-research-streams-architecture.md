# ADR-007: Research Streams Architecture for Persistent Topic Monitoring

**Date:** 2025-09-15  
**Author:** CServinL  
**Status:** Accepted

## Context

Literature review is typically a one-time activity, but researchers often need to **continuously monitor** specific research topics for new papers. The traditional approach requires manual searches and lacks persistence. Researchers need a way to:

- Create persistent research topics that automatically find new papers
- Organize papers using existing tools (Zotero) without disruption  
- Leverage both Collections and Tags for smart organization
- Maintain continuous awareness of evolving research areas

## Decision

We will implement **Research Streams** - a persistent topic monitoring architecture that leverages Zotero Collections and smart tagging for continuous literature discovery.

### Core Concept
```
Research Stream = Zotero Collection + Search Criteria + Smart Tags + Auto-Monitoring
```

### Architectural Principles

1. **Persistence**: Research topics persist beyond single literature reviews
2. **Automation**: Streams automatically discover new papers on schedule
3. **Organization**: Leverage Zotero's Collections + Tags for smart categorization
4. **Non-disruptive**: Works within existing Zotero workflows
5. **Intelligence**: Smart tagging based on content analysis

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

### 3. Automated Workflow
1. **Stream Creation**: User defines topic and search criteria
2. **Initial Population**: Search and save relevant papers to collection
3. **Continuous Monitoring**: Scheduled searches for new papers
4. **Smart Tagging**: Automatic categorization based on content analysis
5. **Deduplication**: Prevent redundant papers across streams
6. **Report Generation**: Generate literature reviews from stream contents

## Benefits

### For Researchers
- **Continuous Awareness**: Stay updated on research areas automatically
- **Organized Discovery**: Papers automatically sorted into collections
- **Cross-topic Analysis**: Tags enable queries across multiple streams
- **Reduced Manual Work**: Automated search and organization

### For Prisma System
- **Persistent Data**: Research topics become long-lived entities
- **Better Organization**: Collections + Tags provide flexible querying
- **Incremental Updates**: Only process new papers, not entire corpus
- **User Engagement**: Researchers interact with system over time

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

### 1. **One-time Literature Reviews Only**
- **Rejected**: Doesn't meet researcher needs for continuous monitoring
- **Problem**: Researchers lose track of new developments

### 2. **External Notification Systems**
- **Rejected**: Adds complexity and doesn't integrate with existing tools
- **Problem**: Creates tool fragmentation

### 3. **Manual Zotero Collections**
- **Rejected**: Lacks automation and smart organization
- **Problem**: Still requires manual search and categorization

## Consequences

### Positive
- **Enhanced User Value**: Continuous monitoring vs. one-time reviews
- **Better Organization**: Structured approach to research topic management
- **Zotero Integration**: Leverages existing user workflows and data
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