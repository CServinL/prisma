# Prisma — Application Ontology

The ontology is the shared language of the system. It defines what exists, what it is called,
how it relates to everything else, and which rules are always true.
It is the contract between the developer, the user, Zotero, and the research domain.

Implementation is incremental — the ontology is not.

Pydantic v2 `BaseModel` is the source of truth for all entities. Documentation describes
invariants; code enforces them.

---

## Mental model

```
                   DISCOVERY LAYER (automatic)
        ┌──────────────────────────────────────────┐
        │  internet sources: arxiv, semanticscholar │
        │  library search: Zotero (shared cache)    │
        └──────────────────┬───────────────────────┘
                           │  PaperMetadata (transient)
                           │  ① bookmark-first: save to library
                           │  ② relevance gate: LLM evaluates vs stream.query
                           ▼
        ┌─────────────────────────────────────────────────┐
        │  Zotero Library (shared across ALL streams)      │
        │                                                   │
        │   ZoteroItem ──── ZoteroCollection (stream A)    │
        │       │       └── ZoteroCollection (stream B)    │
        │       │                                           │
        │  same item, different collections = different    │
        │  perspectives on the same paper                  │
        └───────────────────┬─────────────────────────────┘
                            │  deliberate import: POST /zotero/import/{key}
                            ▼
        ┌─────────────────────────────────────────────────┐
        │  Vault (personal second brain)                   │
        │  Source  Note  Chat  LiteratureReviewReport      │
        │                                                   │
        │  WikiLink · Transclusion · Citation → GraphNode  │
        └──────────────────────────────────────────────────┘
```

The key separation:

| Layer | What it holds | Who writes | Who reads |
|---|---|---|---|
| Internet / library | raw academic papers | external APIs | SearchAgent |
| Zotero library | bookmarks of discovered papers | streams (automatic) | user, streams |
| Zotero collection | papers accepted by ONE stream | stream run | user |
| Vault | things you actively work with | user (via import) | Graphify, Chat |

---

## Entities

| Entity | What it is | Detail |
|---|---|---|
| [Stream](concepts/stream.md) | Named, persistent search subscription | concepts/stream.md |
| [SearchCriteria](concepts/search-criteria.md) | Query + source filters for a stream | concepts/search-criteria.md |
| [PaperMetadata](concepts/paper-metadata.md) | Raw search result from any source (transient) | concepts/paper-metadata.md |
| [PaperSummary](concepts/paper-summary.md) | LLM-analyzed paper with key findings | concepts/paper-summary.md |
| [SmartTag](concepts/smart-tag.md) | Auto-applied label derived from paper content | concepts/smart-tag.md |
| [ZoteroItem](concepts/zotero-item.md) | Bookmark — "we know this paper exists" | concepts/zotero-item.md |
| [ZoteroCollection](concepts/zotero-collection.md) | Stream acceptance journal — papers a stream's LLM gate approved | concepts/zotero-collection.md |
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
| **Stream run** | `Stream.query` → search sources (internet + Zotero library) → per-candidate pipeline (see below) → `ZoteroCollection` updated |
| **Per-candidate pipeline** | ① collection check (already in this stream?) → ② bookmark (add to Zotero library if new) → ③ LLM relevance gate (title + abstract vs stream.query) → ④ add to stream's collection |
| **Library search** | `ZoteroService.search(query)` — queries the Zotero library before (or in parallel with) internet sources; results already have enriched metadata; used as a cheap first pass |
| **Vault import** | `POST /zotero/import/{key}` → `ZoteroItem` + optional PDF → `Source` (.md + companion) |
| **Literature review** | topic → `SearchAgent` → `AnalysisAgent` → `ReportAgent` → `LiteratureReviewReport` → `Note` |
| **DSL rendering** | markdown body → resolve `WikiLink` / `Transclusion` / `Citation` → HTML (server-side, before display) |
| **Graphify indexing** | any vault write → `GraphifyIndexer.mark_stale()` → background re-index → `GraphNode` graph |
| **Note promotion** | chat excerpt selected by user → new `Note` (back-linked via `promoted_from_chat`) |
| **Stream scheduling** | `_StreamScheduler` daemon checks every 5 min; runs any `Stream` where `next_update ≤ now` and `status == active` and `refresh_frequency != manual` |
| **docu-craft conversion** | companion file (PDF, HTML, …) → docu-craft → `.md` body for Graphify + HTML view for UI |

### Stream run — per-candidate pipeline (detailed)

```
For each PaperMetadata from any search source:

  Gate 0 — cross-source dedup:
    Normalize title (lowercase, strip). If already seen in this batch, skip.

  Gate 1 — collection check (fast, no LLM):
    Is this paper already in stream.collection?
    → yes: skip (this stream already accepted it in a prior run)
    → no: proceed

    Note: being in ANY OTHER collection does not count — a paper in the
    "Super Resolution" collection is still a fresh candidate for "Computer Vision".

  Step 2 — bookmark (write to Zotero library if new):
    Is this paper already in the Zotero library?
    → yes: library entry exists, nothing to create
    → no: add_item to Zotero — save bookmark with all available metadata

    Bookmark is saved BEFORE the relevance gate. Finding a paper via academic
    search is sufficient evidence of academic value (Axiom 12).

  Gate 3 — LLM relevance gate (slow, only for candidates that passed Gate 1):
    AnalysisAgent.assess_relevance(title, abstract, stream.query)
    → HIGHLY_RELEVANT / RELEVANT / SOMEWHAT_RELEVANT: accept
    → NOT_RELEVANT: skip (item stays in Zotero library; just not in this collection)
    → UNKNOWN (LLM unavailable): accept by default (fail open, not fail closed)

  Step 4 — accept:
    Add ZoteroItem to stream's ZoteroCollection.
    Increment stream.total_papers.
```

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

12. **Bookmark-first.** Any paper discovered via academic search (internet or library) is saved to the Zotero library before relevance evaluation. Discovery via a targeted query is sufficient evidence of academic value. The relevance gate decides which collection the paper joins — not whether it gets bookmarked.

13. **Relevance is per-stream.** A `ZoteroItem` in collection A is not assumed relevant to stream B. Every stream evaluates every candidate independently against its own query, even if the paper is already bookmarked or in another collection. The same paper can and should appear in multiple collections if relevant to multiple perspectives.

14. **Library search is a first-class source.** The Zotero library is a valid search source for stream runs, equivalent to internet sources. It is preferred for re-runs because its results are already enriched (metadata populated, PDFs attached). New streams should search the library first — a relevant paper may already be bookmarked from another stream.

15. **Collection membership is the acceptance record.** A `ZoteroItem` being in a stream's collection is the only record that the stream's LLM gate accepted it. Absence from a collection means either: the stream hasn't run yet, the paper wasn't found, or the LLM rejected it. These three cases are not distinguished — they are all "not accepted by this stream."

---

## Not yet implemented (in ontology, not in code)

Concepts that belong to the domain and are defined here, but whose code support is partial or missing:

- **SmartTag** — defined in ontology; not yet applied during stream runs or import.
- **PaperSummary per stream item** — produced during `prisma review`; not yet generated per-item during stream runs.
- **Chat** — data model defined; chat API routes not yet implemented.
- **ChromaDB / semantic search** — ADR-009 written; not yet integrated.
- **Async rewrite** — `PrismaCoordinator` and agents are synchronous; `ThreadPoolExecutor` offloads blocking I/O. Full async rewrite deferred.
- **Encryption at rest** — vault files are plaintext. `fscrypt` / `gocryptfs` / `age` deferred.
- **`AnalysisAgent` confidence persistence** — `confidence_score` is computed during search; not saved to `ZoteroItem` or `Source` frontmatter.
