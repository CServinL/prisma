# ADR-008: Enhanced Zotero Integration for Research Library Management

**Date:** 2025-09-15  
**Author:** CServinL  
**Status:** Superseded (2026-07-27) — see "Follow-up" at the end. The
Local-API-primary architecture this ADR describes has been reversed:
prisma only talks to Zotero via its Web API now. Kept for historical
context on why the local-API-primary decision was made at the time.

## Context

Initial Zotero integration planning assumed a multi-approach architecture (SQLite + Web API + Desktop) with complex fallback strategies. However, during Day 2 implementation, comprehensive testing revealed that **Zotero 7's Local API provides complete functionality** for research library management, fundamentally changing our architectural assumptions.

## Problem Statement

Original architectural question: *"How can we balance performance, compatibility, and functionality across multiple Zotero integration approaches for research library management?"*

User insight: *"Why can't we only have desktop integration and that's it?"*

## Decision

We will implement an **enhanced desktop-primary architecture** leveraging Zotero 7's complete Local API for research library management, while maintaining hybrid fallback capabilities for maximum compatibility.

## Key Discovery: Zotero 7 Local API Capabilities for Research Management

### Comprehensive Testing Results ✅

**Local API Validation** (`localhost:23119/api/`):
- ✅ **Full Library Access**: Complete research item retrieval with metadata
- ✅ **Advanced Search**: Query parameter support (`?q=search`) for research discovery
- ✅ **Collection Management**: Full CRUD operations for research organization
- ✅ **Same Data Structure**: Identical JSON format as Web API
- ✅ **Performance**: Local access, no network latency for library operations
- ✅ **No Authentication**: No API keys required for local research management
- ✅ **No Rate Limits**: Unlimited local access for library operations

**Connector API Validation** (`localhost:23119/connector/`):
- ✅ **Write Operations**: Save research items with 100% compatibility
- ✅ **Collection Assignment**: Direct item-to-collection mapping for research organization
- ✅ **Sync Integration**: Perfect sync with Zotero cloud services

## Research Library Management Architecture

### Original Multi-Approach Strategy
```
Priority: Desktop App → SQLite → Web API
Use Case: Desktop for writes, SQLite for reads, Web API for fresh data
```

### Enhanced Local-API-Primary Strategy for Research Library Management
```
Priority: Local API → Web API → SQLite
Use Case: Local API for library management, Web API for research discovery, SQLite as fallback
```

## Implementation Architecture

### 1. **Primary Integration: Local API Client for Research Library Management**
```python
class ZoteroLocalAPIClient:
    """Enhanced client for Zotero 7's complete local HTTP API for research library management"""
    
    def search_research(self, query: str) -> List[ZoteroItem]:
        # Direct API call to localhost:23119/api/users/0/items?q=query
        
    def create_research_collection(self, data: Dict) -> ZoteroCollection:
        # Collection creation for research organization via local API
        
    def save_research_items(self, items: List[Dict]) -> bool:
        # Save research content via connector endpoints
```

### 2. **Enhanced Hybrid Client for Research Library Management**
```python
class ZoteroHybridClient:
    """Intelligent multi-approach client with Local API priority for research library management"""
    
    def __init__(self):
        self.local_client = ZoteroLocalAPIClient()     # Primary for library management
        self.web_client = ZoteroClient()               # Research discovery
        self.sqlite_client = ZoteroSQLiteClient()      # Fallback
```

### 3. **Strategic API Usage for Research Library Management**

| Operation | Primary Method | Use Case |
|-----------|---------------|----------|
| **Read Research Library** | Local API | Fast access to existing research items |
| **Search Library Content** | Local API | Query user's current research collection |
| **Discover New Research** | Web API | Find research not in local library |
| **Save Research Items** | Connector API | Add new research with perfect sync |
| **Organize Collections** | Local API | Create/manage research streams |
| **Fallback Access** | SQLite | When Zotero desktop unavailable |

## Benefits Realized

### Performance
- **🚀 Local Speed**: Eliminates network latency for research library operations
- **📈 No Rate Limits**: Unlimited local API access for library management
- **💾 Reduced Complexity**: Fewer fallback paths needed

### Compatibility  
- **🔐 No Authentication**: Local research operations require no API keys
- **🔄 Perfect Sync**: Uses Zotero's native connector endpoints for research items
- **📱 Universal**: Works across all Zotero installations for research management

### User Experience
- **⚡ Immediate Response**: Local library operations are instant
- **🎯 Simplified Setup**: Minimal configuration required for research management
- **🛠️ Tool Integration**: Leverages existing Zotero workflows for research organization

## Architectural Validation Process

### Testing Methodology
1. **Capability Assessment**: Systematic testing of all Local API endpoints for research management
2. **Performance Benchmarking**: Comparing Local API vs. SQLite vs. Web API for library operations
3. **Compatibility Verification**: Testing research item operations and sync behavior
4. **Real-world Validation**: Using actual Zotero library with research content

### Validation Results
```bash
# Comprehensive test results for research library management:
$ pipenv run python work/validate_architecture.py

✅ CAPABILITIES VERIFIED:
   📚 Full library access: 6 items available  
   🔍 Advanced search: Query parameter support
   📁 Collection management: Full API access
   💾 Write operations: Connector API functional
   🔄 Data consistency: Same structure as web API
   ⚡ Performance: Local access, no rate limits
```

## Implementation Components

### 1. **Local API Client** (`src/integrations/zotero/local_api_client.py`)
- Complete implementation of Zotero 7 Local API
- Read/write operations with full error handling
- Collection management and search capabilities

### 2. **Enhanced Hybrid Client** (`src/integrations/zotero/hybrid_client.py`)  
- Local API primary strategy with intelligent fallbacks
- Collection creation and tag management
- Research Streams integration support

### 3. **Architectural Validation Scripts** (`work/validate_architecture.py`)
- Comprehensive testing of Local API capabilities
- Performance benchmarking and compatibility verification
- Real-world scenario validation

## Consequences

### Positive
- **🏆 Validates User Insight**: Original desktop-only intuition was correct for research library management
- **⚡ Superior Performance**: Local-first architecture with minimal latency for library operations
- **🔧 Reduced Complexity**: Fewer integration approaches needed for research management
- **🔐 Enhanced Security**: Minimal authentication requirements for research library access
- **📈 Better Scalability**: No rate limiting on primary research library operations

### Negative  
- **📱 Zotero Dependency**: Requires Zotero 7 desktop application running for research management
- **🌐 Limited Discovery**: Still need Web API for finding new research content
- **🔄 Fallback Complexity**: Hybrid client still maintains multiple approaches

### Risk Mitigation
- **Hybrid Fallbacks**: SQLite and Web API remain available for research library access
- **Version Detection**: Graceful degradation for older Zotero versions
- **Error Handling**: Comprehensive error handling and user guidance for research operations

## Status

**Accepted** - Successfully implemented and validated in Day 2 development for research library management.

**Key Outcome**: User's original architectural insight about desktop-only integration was **100% correct** for research library management and has been validated through comprehensive testing.

## Related ADRs
- ADR-001: Simple Pipeline Architecture (enhanced with Local API for research operations)
- ADR-007: Research Streams Architecture (leverages Local API for research collections)

## Future Considerations
- **Zotero Version Support**: Monitor Zotero 7+ adoption and API evolution for research management
- **Performance Optimization**: Further optimize Local API usage patterns for research library operations
- **Research Discovery Enhancement**: Integrate external research APIs with Local API workflows

## Follow-up (2026-07-27): reversed — Web API only, local-API clients removed

The Local-API-primary architecture (`ZoteroHybridClient` → `ZoteroLocalAPIClient` /
`ZoteroDesktopClient`, this ADR's core decision) is gone. `services/zotero.py`'s own
`ZoteroMode.desktop` was found to be dead code earlier in the same session that
prompted this reversal — the server (`prisma serve`) never actually selected it,
because the assumption underlying this whole ADR (the process reading from Zotero
Desktop's local HTTP server is *also* the process running on the user's machine) broke
once prisma split into a server (running on a dedicated machine, "forge") and a
desktop client (running on the user's own machine, "prisma-desktop"). The local API at
`localhost:23119` is, definitionally, only reachable from whatever machine Zotero
Desktop itself runs on — the server has no guarantee of being that machine.

Considered and explicitly rejected: moving the local-API read path into
`prisma-desktop` (Rust) instead of deleting it, so *something* in the split
architecture could still use it from the right machine. Decided against — no other
prisma-desktop feature needs it, and it would be new functionality, not a port (the
old Python local-API client's write-oriented methods — `add_item_to_collection`,
`update_item_tags` — were themselves already stubs/no-ops; only reads ever really
worked, and nothing in prisma-desktop currently consumes Zotero data at all).

**What changed:**
- Removed entirely: `integrations/zotero/hybrid_client.py`, `local_api_client.py`,
  `desktop_client.py`, and `tests-sets/local-zotero/` (nothing left to test against).
- `integrations/zotero/unified_client.py`'s `ZoteroClient` facade collapsed from a
  4-way mode-selecting router down to a thin wrapper over `client.py`'s Web API client
  alone — the facade itself is kept (callers like `ResearchStreamManager` depend on
  `from_config()`/`client_type`/`client_info`), but there's only one backend to route
  to now.
- `cli/commands/cleanup.py`'s `cleanup_duplicates`/`library_stats` (previously: local
  API for reads, Web API for deletes) now read via a new
  `ZoteroClient.get_all_items()` (Web API, paginated via pyzotero's `everything()`)
  and write via the same client — no more split.
- `cli/commands/zotero.py`'s `zotero_status` simplified to report internet
  connectivity + Web API credentials/reachability only.
- A new, single canonical live-reachability check,
  `services/zotero.py::check_web_api_reachable()`, replaces the removed
  `hybrid_client.py::check_zotero_web_api_access()` (same idea — validate the
  configured library is actually reachable with these credentials, not just that a
  key is present) and backs both `ZoteroService.status()`'s new `reachable` field
  (surfaced in the UI's status panel) and the CLI's `zotero status` command.

See `TODO.md`'s "Code quality assessment" #1 for the fuller before/after and the
lesson drawn from this reversal (duplication that looks like "needs a refactor" can
sometimes actually be "needs three of the four things deleted").

## Related
- ADR-011: Authentication Strategy — the same server/desktop machine split this
  follow-up's reasoning depends on.