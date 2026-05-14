# ADR-003: Enhanced Composition for Research Library Management

**Date:** 2025-09-15 (Updated: 2025-09-17)  
**Author:** CServinL  
**Status:** Evolved

## Context

Our Research Library Assistant has evolved from simple document processing to a comprehensive library management system with Research Streams, Zotero integration, and AI-powered research organization. We need a composition approach that handles this research-focused complexity while maintaining clarity.

## Decision Evolution

**Original**: Simple direct composition for document processing pipeline  
**Current**: Enhanced composition with research library services and intelligent curation

### Current Implementation Approach
- Components organized around research library management workflows
- Research Stream Manager as core persistent service for library organization
- Zotero clients managed as research collection infrastructure
- AI components focused on research assistance and library curation

### Enhanced Research Library Structure
```python
class ResearchLibraryAssistant:
    def __init__(self, debug: bool = False):
        # Core research discovery and organization
        self.discovery_engine = ResearchDiscoveryEngine()
        self.ai_assistant = AIResearchAssistant()
        self.library_organizer = LibraryOrganizationSystem()
        
        # Enhanced Zotero integration for research collections
        self.zotero_manager = None
        if config.get('sources.zotero.enabled', False):
            self.zotero_manager = ZoteroLibraryManager(config.get('sources.zotero'))
    
    def curate_research_stream(self, stream_config):
        # Enhanced research library workflow
        discovered_research = self.discovery_engine.discover_multi_source(stream_config)
        relevant_research = self.ai_assistant.assess_research_relevance(discovered_research)
        curated_research = self._organize_research_collection(relevant_research)
        new_research = self._manage_library_duplicates(curated_research)
        research_insights = self.ai_assistant.generate_research_insights(new_research)
        organized_library = self.library_organizer.update_collections(research_insights, stream_config)
        return organized_library

class ResearchStreamManager:
    def __init__(self, zotero_manager: ZoteroLibraryManager):
        self.zotero_manager = zotero_manager
        self._research_streams_cache = {}
    
    def create_research_stream(self, config: ResearchStreamConfig) -> ResearchStream:
        # Enhanced research stream creation with library organization
        pass
```

## Enhanced Benefits for Research Library Management
- **Research-focused architecture**: Components organized around library management workflows
- **Persistent research organization**: Research streams maintain long-term library state
- **AI-powered curation**: Intelligent research discovery and organization assistance
- **Zotero-centric design**: Deep integration with researcher's existing library infrastructure

## Current Trade-offs
- **Research domain complexity**: More sophisticated than generic document processing
- **Library integration dependency**: Requires Zotero for full research organization capabilities
- **AI dependency**: Relies on AI for research curation and insights generation

## Evolution Rationale for Research Assistance
The system has evolved to become a true Research Library Assistant:
- **Research Streams**: Persistent research topic monitoring and library building
- **Library Management**: Sophisticated Zotero collection organization and curation
- **AI Research Assistance**: Intelligent research discovery, relevance assessment, and insights
- **Research Workflows**: Designed specifically for academic and professional researchers

Direct composition still works effectively, but now operates as a research-focused service layer rather than generic document processing.

## When to Revisit
- If we add collaborative research features requiring distributed architecture
- If we need complex research workflow orchestration beyond current library management
- If research collection management becomes significantly more complex
- If we need runtime switching between different research methodologies or approaches  
**Author**: Development Team  
**Reviewers**: Architecture Review Board
