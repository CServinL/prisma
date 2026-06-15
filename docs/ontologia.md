# Prisma — Application Ontology

The ontology is the shared language of the system. It defines what exists, what it is called,
how it relates to everything else, and which rules are always true.
It is the contract between the developer, the user, Zotero, and the research domain.

Implementation is incremental — the ontology is not.

Pydantic v2 `BaseModel` is the source of truth for all entities. Documentation describes
invariants; code enforces them.

---

## Entity Map

```
Stream ─────── SearchCriteria
  │
  │  on each run: SearchAgent fetches PaperMetadata
  │
  ▼
ZoteroCollection                          ← bookmark layer
  │
  │  + ZoteroItem per paper found
  │
  │  deliberate import: POST /zotero/import/{key}
  ▼
Source (.md in vault)                     ← second brain
  │  zotero_key back-links to ZoteroItem
  │
  ▼
Note  ·  Chat  ·  LiteratureReviewReport  ← personal layer
  │         │
  └────┬────┘
       │  all indexed by
       ▼
  GraphNode (Graphify)
  WikiLink · Transclusion · Citation      ← graph edges
       │
  GraphCluster
```

---

## Entities

| Entity | What it is | Detail |
|---|---|---|
| [Stream](concepts/stream.md) | Named, persistent search subscription | concepts/stream.md |
| [SearchCriteria](concepts/search-criteria.md) | Query + source filters for a stream | concepts/search-criteria.md |
| [PaperMetadata](concepts/paper-metadata.md) | Raw search result from an academic source | concepts/paper-metadata.md |
| [PaperSummary](concepts/paper-summary.md) | LLM-analyzed paper with key findings | concepts/paper-summary.md |
| [SmartTag](concepts/smart-tag.md) | Auto-applied label derived from paper content | concepts/smart-tag.md |
| [ZoteroCollection](concepts/zotero-collection.md) | Folder in Zotero grouping a stream's items | concepts/zotero-collection.md |
| [ZoteroItem](concepts/zotero-item.md) | Full Zotero record — the bookmark layer | concepts/zotero-item.md |
| [Source](concepts/source.md) | External content deliberately imported into the vault | concepts/source.md |
| [Note](concepts/note.md) | Personal, editable synthesis — the intellectual layer | concepts/note.md |
| [Chat](concepts/chat.md) | Saved LLM session grounded in vault nodes | concepts/chat.md |
| [LiteratureReviewReport](concepts/literature-review-report.md) | Output of the full review pipeline | concepts/literature-review-report.md |
| [WikiLink](concepts/wiki-link.md) | `[[slug]]` DSL — navigate to a vault node | concepts/wiki-link.md |
| [Transclusion](concepts/transclusion.md) | `![[slug]]` DSL — embed node content inline | concepts/transclusion.md |
| [Citation](concepts/citation.md) | `[[@citekey]]` DSL — reference a Source | concepts/citation.md |
| [GraphNode](concepts/graph-node.md) | Vault node as a vertex in the knowledge graph | concepts/graph-node.md |
| [Job](concepts/job.md) | Async literature review task (server-side) | concepts/job.md |

---

## Mechanics

| Mechanic | What it does |
|---|---|
| **Stream run** | `Stream.query` → `SearchAgent` → `PaperMetadata[]` → confidence filter → `ZoteroCollection` + `ZoteroItem` per paper |
| **Vault import** | `POST /zotero/import/{key}` → `ZoteroItem` + optional PDF → `Source` (.md + companion) |
| **Literature review** | topic → `SearchAgent` → `AnalysisAgent` → `ReportAgent` → `LiteratureReviewReport` → `Note` |
| **DSL rendering** | markdown body → resolve `WikiLink` / `Transclusion` / `Citation` → HTML (server-side, before display) |
| **Graphify indexing** | any vault write → `GraphifyIndexer.mark_stale()` → background re-index → `GraphNode` graph |
| **Note promotion** | chat excerpt selected by user → new `Note` (back-linked via `promoted_from_chat`) |
| **Stream scheduling** | `_StreamScheduler` daemon checks every 5 min; runs any `Stream` where `next_update ≤ now` and `status == active` and `refresh_frequency != manual` |
| **docu-craft conversion** | companion file (PDF, HTML, …) → docu-craft → `.md` body for Graphify + HTML view for UI |

---

## Axioms

Rules that are always true. Not preferences — invariants.

1. **Sources are immutable.** A `Source` is never edited in place. Notes derived from it are.

2. **Streams expand, never contract.** Each run adds items to the `ZoteroCollection`. Nothing is removed from a prior run.

3. **Every `LiteratureReviewReport` becomes a `Note`.** Reviews are not ephemeral — they are saved to the vault and indexed.

4. **Stream runs write to Zotero, not to the vault.** The `ZoteroCollection` is the canonical store for stream papers. Vault `Source` nodes only come from deliberate import (`POST /zotero/import/{key}`). Do not auto-populate the vault from stream runs.

5. **Chats are grounded.** A chat session uses only vault nodes as context — no external retrieval at chat time.

6. **Broken citations surface.** A `[[@citekey]]` with no matching `Source` renders as a visible warning, never silently dropped.

7. **Transclusion depth ≤ 5.** Guards against circular embeds crashing the renderer.

8. **Graphify re-indexes on save.** After any `Note` or `Source` write, `mark_stale()` is called — the graph is always fresh within one cycle.

9. **`slug` is stable.** Once assigned, a node's slug never changes — all DSL links remain valid.

10. **Every `Source` has a `.md`; the companion is optional.** The `.md` is always created (manually or via docu-craft). It is what Graphify indexes and what DSL links point to. The companion (`.pdf`, `.html`, `.svg`, …) is the original rich format for human reading.

11. **Every `Source` has a `zotero_key`.** Sources enter the vault only via Zotero import. The key is the permanent back-link to the `ZoteroItem`.

---

## Not yet implemented (in ontology, not in code)

Concepts that belong to the domain and are defined here, but whose code support is partial or missing:

- **`Stream.collection_key`** — field exists on the model; `_run_stream` does not yet create the `ZoteroCollection` or add items. Stream runs write nothing to Zotero today. This violates Axiom 4 and must be corrected.
- **`SmartTag`** — defined in ontology; not yet applied during stream runs or import.
- **`PaperSummary`** — produced during `prisma review`; not yet generated per-item during stream runs.
- **`Chat`** — data model defined; chat API routes not yet implemented.
- **ChromaDB / semantic search** — ADR-009 written; not yet integrated.
- **Async rewrite** — `PrismaCoordinator` and agents are synchronous; `ThreadPoolExecutor` offloads blocking I/O. Full async rewrite deferred.
- **Encryption at rest** — vault files are plaintext. `fscrypt` / `gocryptfs` / `age` deferred.
- **`AnalysisAgent` confidence persistence** — `confidence_score` is computed during search; not saved to `ZoteroItem` or `Source` frontmatter.
