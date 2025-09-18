# Zotero Integration Guide

Prisma provides **next-generation Zotero integration** with persistent research monitoring through **Research Streams** and **intelligent network-aware operation**.

## 🌐 Network-Aware Architecture

Prisma's Zotero integration automatically adapts to your network connectivity, providing seamless operation both online and offline.

### 🟢 Online Mode (Internet Available)
When connected to the internet and Zotero Web API is accessible:

**📖 Read Operations**: **Web API (Preferred)** → Local HTTP (Fallback)
- **Primary**: Zotero Web API (`api.zotero.org`) for most up-to-date data
- **Fallback**: Local HTTP API (`localhost:23119`) if Web API fails
- **Benefits**: Latest synced data from all devices, real-time updates

**✍️ Write Operations**: **Web API Only**
- **Source**: Zotero Web API (`api.zotero.org`)
- **Operations**: Create items/collections, delete, modify metadata
- **Benefits**: Guaranteed sync across devices, conflict resolution, data integrity

### 🔴 Offline Mode (No Internet)
When internet is unavailable or Zotero Web API is inaccessible:

**📖 Read Operations**: **Local HTTP Only**
- **Source**: Zotero 7's Local HTTP API (`localhost:23119/api/`)
- **Operations**: Search items, get collections, retrieve metadata
- **Benefits**: Continue working with local library data, no network dependency

**✍️ Write Operations**: **🚫 DISABLED**
- **Behavior**: All write operations are automatically disabled
- **Reason**: Prevents data inconsistencies and sync conflicts
- **User Experience**: Clear error messages explaining offline limitations

### 🎯 Core Principle
> **Smart Network Awareness**
> 
> - 🟢 **Online**: Web API preferred for freshest data + writes enabled
> - 🔴 **Offline**: Local HTTP only for reads + writes safely disabled
> - 🔄 **Auto-Detection**: Seamless switching based on connectivity

## 🌊 Research Streams: Persistent Topic Monitoring

**Research Streams** are persistent research topics that automatically monitor for new papers using smart Zotero Collections and Tags.

### Core Concept
```
Research Stream = Zotero Collection + Smart Tags + Auto-Monitoring
├── Collection: "Neural Networks 2024" 
├── Search Query: "neural networks transformer attention"
├── Smart Tags: prisma-auto, year-2024, type-survey
├── Auto-Refresh: Weekly
└── Continuous Discovery: New papers → Auto-tagged → Added to collection
```

## 🔧 Integration Configuration

### Network-Aware Hybrid Mode (Recommended)
```yaml
sources:
  zotero:
    mode: "hybrid"
    
    # Network behavior
    prefer_web_api_when_online: true        # Use Web API when internet available
    disable_writes_when_offline: true       # Safety: no writes when offline
    network_check_interval: 30              # Check connectivity every 30 seconds
    
    # Local HTTP server (for offline reads)
    local_server_url: "http://127.0.0.1:23119"
    local_server_timeout: 5
    
    # Web API (for online reads and all writes)
    api_key: "your_zotero_api_key"
    library_id: "your_library_id"
    library_type: "user"  # or "group"
    
    # Organization
    collections: ["AI Research", "Edge Computing"]
```

### Local HTTP Only (Offline-Only Mode)
For scenarios where you only need read-only access and never want network requests:

```yaml
sources:
  zotero:
    mode: "local_api"
    server_url: "http://127.0.0.1:23119"
    collections: ["AI Research", "Edge Computing"]
    # Note: Write operations will always fail in this mode
```

## 📊 Network-Aware Operation Matrix

### Online Mode (🟢 Internet Available)
| Operation Type | Primary Client | Fallback | Purpose | Write Protection |
|---------------|----------------|----------|---------|------------------|
| **Search Items** | Web API | Local HTTP | Latest synced results | N/A (read-only) |
| **Get Collections** | Web API | Local HTTP | Current collection state | N/A (read-only) |
| **Get Item Details** | Web API | Local HTTP | Most recent metadata | N/A (read-only) |
| **Create Collection** | Web API | None | Synced creation | ✅ **Enabled** |
| **Create Item** | Web API | None | Reliable item creation | ✅ **Enabled** |
| **Delete Operations** | Web API | None | Safe deletion with sync | ✅ **Enabled** |
| **Add to Collection** | Web API | None | Synced collection updates | ✅ **Enabled** |
| **Modify Metadata** | Web API | None | Conflict-free updates | ✅ **Enabled** |

### Offline Mode (🔴 No Internet)
| Operation Type | Available Client | Behavior | Limitation |
|---------------|------------------|----------|------------|
| **Search Items** | Local HTTP | ✅ **Works with local data** | May be outdated |
| **Get Collections** | Local HTTP | ✅ **Works with local data** | May be outdated |
| **Get Item Details** | Local HTTP | ✅ **Works with local data** | May be outdated |
| **Create Collection** | None | 🚫 **Disabled** | "Offline: writes disabled" |
| **Create Item** | None | 🚫 **Disabled** | "Offline: writes disabled" |
| **Delete Operations** | None | 🚫 **Disabled** | "Offline: writes disabled" |
| **Add to Collection** | None | 🚫 **Disabled** | "Offline: writes disabled" |
| **Modify Metadata** | None | 🚫 **Disabled** | "Offline: writes disabled" |

### 🛡️ Automatic Network Detection
The system continuously monitors:
- **Internet Connectivity**: Basic network access
- **Zotero Web API Access**: Specific API endpoint availability
- **Fallback Strategy**: Graceful degradation when services become unavailable

### ✅ Write Operation Verification (Online Only)
**When online, all write operations include immediate verification:**

1. **Execute Write**: Perform operation via Web API
2. **Immediate Check**: Verify the change via Web API within the same request cycle
3. **Confirm Success**: Only return success when verification confirms completion
4. **No Sync Wait**: Eliminates waiting for background sync processes
