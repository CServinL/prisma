# Prisma — Application Ontology

Cross-repo ontology covering `prisma` (server), `prisma-desktop` (UI), and their integration with Graphify, docu-craft, and Zotero.

Pydantic v2 `BaseModel` is the source of truth for all entities. Documentation describes invariants; code enforces them.

---

## Entity Map

```
ResearchStream ──── SearchCriteria
      │                   │
      │ expands over time  │ yields
      ▼                   ▼
 ZoteroCollection ◄── PaperMetadata / BookMetadata
      │                   │
      │                   │ LLM analysis
      │                   ▼
      │              PaperSummary
      │                   │
      │                   ▼
      └──────────► Source (vault node)  ◄── ZoteroItem
                         │
                         │  lives alongside
                         ▼
                   Note  ·  Chat        ← personal layer
                    │         │
                    └────┬────┘
                         │  all indexed by
                         ▼
                   GraphNode (Graphify)
                    │    │    │
              WikiLink  Transclusion  Citation  ← edges
                         │
                    GraphCluster
```

---

## Tiers

### Tier 1 — Research Engine (`prisma`)

The original Prisma core: automated literature discovery.

#### `ResearchStream`

A **Stream** is a named, persistent search subscription.

- On **first run**: fetches an initial set of papers matching `SearchCriteria`.
- On **subsequent runs**: expands the set — both *forward* (papers published since last run) and *backward* (older papers not yet captured, up to `lookback_limit`).
- Each paper found → saved to `ZoteroCollection` + materialised as a `Source` in the vault.
- The stream's `ZoteroCollection` is the canonical store for its papers.

| Field | Type | Description |
|---|---|---|
| `id` | str | URL-safe slug |
| `name` | str | Human name |
| `description` | str \| None | Optional |
| `search_criteria` | `SearchCriteria` | Query + filters |
| `collection_key` | str | Zotero collection key |
| `collection_name` | str | Zotero collection name |
| `parent_collection_key` | str \| None | Nested under a parent |
| `status` | `StreamStatus` | active \| paused \| archived |
| `refresh_frequency` | `RefreshFrequency` | daily \| weekly \| monthly \| manual |
| `lookback_limit` | int | Max papers to pull backward per run (default 50) |
| `last_updated` | datetime \| None | |
| `next_update` | datetime \| None | |
| `total_papers` | int | Cumulative count |
| `new_papers_last_update` | int | Delta from last run |
| `smart_tags` | list[`SmartTag`] | Auto-applied on ingestion |
| `created_at` | datetime | |
| `created_by` | str \| None | |

#### `SearchCriteria`

| Field | Type |
|---|---|
| `query` | str |
| `tags` | list[str] |
| `exclude_tags` | list[str] |
| `item_types` | list[str] |
| `since_date` | date \| None |
| `max_results` | int |

#### `SmartTag`

| Field | Type |
|---|---|
| `name` | str |
| `category` | `TagCategory` |
| `auto_generated` | bool |
| `description` | str \| None |

#### `PaperMetadata` / `BookMetadata`

Raw output from search agents. Normalised, not yet analysed.

Key fields: `title`, `authors`, `abstract`, `source`, `url`, `published_date`, `doi`, `arxiv_id`.

#### `PaperSummary`

LLM-analysed paper: adds `summary`, `key_findings`, `methodology`, `analysis_confidence`.

#### `ZoteroItem`

Full Zotero record. `key` is globally unique. Has `creators`, `tags`, `collections`, `attachments`.

#### `LiteratureReviewReport`

Output of the full pipeline (SearchAgent → AnalysisAgent → ReportAgent). Contains `content` (Markdown). Always saved as a `Note` in the vault — never ephemeral.

#### Enums

| Enum | Values |
|---|---|
| `StreamStatus` | active \| paused \| archived |
| `RefreshFrequency` | daily \| weekly \| monthly \| manual |
| `TagCategory` | prisma \| temporal \| methodology \| status \| quality \| source |
| `ZoteroItemType` | journal_article \| book \| book_section \| conference_paper \| thesis \| report \| webpage \| preprint \| manuscript \| presentation \| other |
| `SourceQuality` | ⭐⭐⭐⭐⭐ semantic_scholar / arxiv → ⭐ manual forms |

---

### Tier 2 — Vault (`prisma` server, `prisma-desktop` UI)

Everything that lives on disk as a `.md` file in the user's vault directory.

#### `VaultNode` (abstract base)

All vault content shares this base.

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe unique identifier, derived from filename |
| `title` | str | Display name |
| `node_type` | `NodeType` | note \| source \| chat |
| `tags` | list[str] | `#tag` markers |
| `created_at` | datetime | |
| `modified_at` | datetime | |
| `path` | Path | Absolute path on disk |

#### `Note` (extends `VaultNode`)

Personal, editable. The intellectual layer — synthesis, ideas, mind maps.

| Field | Type |
|---|---|
| `node_type` | `NodeType.note` |
| `body` | str | Raw markdown with DSL |
| `status` | `NoteStatus` | draft \| active \| archived |
| `promoted_from_chat` | str \| None | Chat slug if promoted from a chat excerpt |

#### `Source` (extends `VaultNode`)

External content, read-only. Papers, PDFs, HTML pages, SVGs, EPUBs, and other documents pulled in from Zotero or uploaded.

Every `Source` **always** has a `<slug>.md` — the canonical form for Graphify indexing and DSL linking. It optionally has a **companion file** (`<slug>.pdf`, `<slug>.html`, `<slug>.svg`, `<slug>.epub`, `<slug>.docx`, …) — the original rich format for human reading.

**Conversion pipeline (docu-craft):** When a non-markdown original arrives, docu-craft converts it to `.md` and renders a human-readable HTML view. The `.md` is what Prisma reasons over; the companion is what humans open for rich viewing.

| Field | Type | Description |
|---|---|---|
| `node_type` | `NodeType.source` | |
| `source_kind` | `SourceKind` | paper \| document \| web \| media |
| `origin` | `SourceOrigin` | zotero \| upload \| url (metadata origin) |
| `citekey` | str | Used in `[[@citekey]]` DSL |
| `zotero_key` | str \| None | Links back to `ZoteroItem.key` for metadata sync |
| `stream_id` | str \| None | Stream that discovered this source |
| `abstract` | str \| None | |
| `authors` | list[str] | |
| `year` | int \| None | |
| `doi` | str \| None | |
| `body` | str | Content of the `.md` file (extracted/converted text) |
| `original_ext` | str \| None | Extension of the companion file, e.g. `.pdf`, `.html`, `.svg` |

#### `Chat` (extends `VaultNode`)

Saved LLM session. Grounded in vault nodes — no hallucination beyond graph context.

| Field | Type |
|---|---|
| `node_type` | `NodeType.chat` |
| `messages` | list[`ChatMessage`] | Full turn history |
| `context_slugs` | list[str] | Vault nodes used as context |
| `model` | str | Ollama model name |
| `promoted_excerpts` | list[str] | Note slugs promoted from this chat |

#### `ChatMessage`

| Field | Type |
|---|---|
| `role` | `ChatRole` | user \| assistant |
| `content` | str | |
| `timestamp` | datetime | |
| `sources_cited` | list[str] | Citekeys referenced in this turn |

#### Enums

| Enum | Values |
|---|---|
| `NodeType` | note \| source \| chat |
| `SourceKind` | paper \| document \| web \| media |
| `SourceOrigin` | zotero \| upload \| url |
| `NoteStatus` | draft \| active \| archived |
| `ChatRole` | user \| assistant |

---

### Tier 3 — DSL (`prisma` renderer, docu-craft)

Notation embedded in `.md` bodies. Resolved server-side before md → HTML conversion.

| Notation | Entity | Meaning |
|---|---|---|
| `[[slug]]` | `WikiLink` | Navigate to vault node |
| `[[slug#section]]` | `WikiLink` | Link to a section |
| `![[slug]]` | `Transclusion` | Embed full node content inline |
| `![[slug#section]]` | `Transclusion` | Embed one section |
| `[[@citekey]]` | `Citation` | Reference a Source; resolves to its vault node |
| `#tag` | `Tag` | Label; indexes the node in the graph |

#### `WikiLink`

| Field | Type |
|---|---|
| `source_slug` | str | Node containing the link |
| `target_slug` | str | Node being linked |
| `section` | str \| None | Target section anchor |
| `resolved` | bool | False if target not found |

#### `Transclusion`

| Field | Type |
|---|---|
| `source_slug` | str | |
| `target_slug` | str | |
| `section` | str \| None | |
| `depth` | int | Current recursion depth (max 5) |

#### `Citation`

| Field | Type |
|---|---|
| `source_slug` | str | Note/chat containing the citation |
| `citekey` | str | Must resolve to a `Source.citekey` |
| `resolved` | bool | False if Source not found |

---

### Tier 4 — Knowledge Graph (`graphify`)

Graphify indexes all vault nodes and their DSL links into a queryable graph.

| Entity | Description |
|---|---|
| `GraphNode` | One vault node (`Note`, `Source`, or `Chat`) as a graph vertex |
| `GraphEdge` | One DSL link (`WikiLink`, `Transclusion`, `Citation`) as a directed edge |
| `GraphCluster` | Community of related nodes (Graphify Leiden/community detection) |
| `GodNode` | Most connected / central concept node in the graph |

Edge types also include **implicit edges** derived by Graphify:
- Co-authorship (two Sources sharing an author)
- Co-citation (two Sources cited together in the same Note/Chat)
- Semantic similarity (above threshold, no explicit link needed)

---

### Config

#### `VaultConfig`

| Field | Type | Default |
|---|---|---|
| `vault_path` | Path | `{server_root}/notes/` |
| `zotero` | `ZoteroConfig` | see prisma config |
| `ollama_host` | str | `http://localhost:11434` |
| `graphify_out` | Path | `vault_path/.graphify-out/` |
| `default_model` | str | `llama3` |

---

## Axioms

1. **Sources are immutable.** A `Source` is never edited — only `Note`s derived from it are.
2. **Streams expand, never contract.** Each stream run adds papers; it never removes previously found ones.
3. **Every `LiteratureReviewReport` becomes a `Note`.** Reviews are not ephemeral — they are saved to the vault and indexed by Graphify.
4. **Every stream paper becomes a `Source`.** Each `ZoteroItem` discovered by a stream is materialised as a `Source` in the vault.
5. **Chats are grounded.** A chat session uses only vault nodes as context — no external retrieval at chat time.
6. **Broken citations surface.** A `[[@citekey]]` with no matching `Source` renders as a visible warning, never silently dropped.
7. **Transclusion depth ≤ 5.** Guards against circular embeds.
8. **Graphify re-indexes on save.** After any `Note` or `Source` write, Graphify re-indexes in the background — the graph is always fresh.
9. **`slug` is stable.** Once assigned, a node's slug never changes — all links remain valid.
10. **Every source has a `.md`; the companion is optional.** The `.md` is always created (by hand or via docu-craft conversion) — it is what Graphify indexes and what DSL links point to. The companion file (`<slug>.pdf`, `<slug>.html`, etc.) is the original rich format, stored alongside the `.md` in `sources/`. On Zotero import: if Zotero has the attachment, it is copied to the vault as the companion and docu-craft produces the `.md`. If Zotero has only metadata, only the `.md` is created. `GET /notes/<slug>/original` serves the companion file to the UI.

---

## Cross-Repo Ownership

| Layer | Owned by | Consumed by |
|---|---|---|
| Research Engine (Tier 1) | `prisma` | `prisma-desktop`, `prisma` CLI |
| Vault + DSL (Tiers 2–3) | `prisma` server | `prisma-desktop` |
| Knowledge Graph (Tier 4) | `graphify` | `prisma` server |
| Rendering (md→HTML) | `docu-craft` | `prisma` server |
| UI | `prisma-desktop` | — |
