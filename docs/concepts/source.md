# Source

## What it is

A **Source** is external content that has been deliberately imported into the vault.
It is the second-brain layer — it means *I am actively working with this.*

A `Source` is always backed by a `ZoteroItem`. The import action copies the item's metadata,
fetches the PDF or HTML if available, and converts it to a `.md` file via docu-craft.
From that point on, the vault owns a local, searchable, linkable copy.

Sources are read-only. You annotate and synthesise in [Notes](note.md); you do not edit
the source itself.

## Files on disk

Every `Source` has exactly one `.md` file in `vault/sources/`. This is what Graphify indexes
and what DSL links (`[[@citekey]]`) point to.

Optionally, a companion file lives alongside it (`<slug>.pdf`, `<slug>.html`, `<slug>.svg`, …).
The companion is the original rich format, served to the UI via `GET /notes/{slug}/original`.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier, stable forever |
| `title` | str | Paper/document title |
| `citekey` | str | Used in `[[@citekey]]` DSL |
| `zotero_key` | str \| None | Back-link to the originating `ZoteroItem` |
| `stream_id` | str \| None | Stream that originally discovered this source (informational) |
| `source_kind` | `SourceKind` | `paper` \| `document` \| `web` \| `media` |
| `origin` | `SourceOrigin` | `zotero` \| `upload` \| `url` |
| `authors` | list[str] | Author names |
| `year` | int \| None | Publication year |
| `doi` | str \| None | DOI |
| `abstract` | str \| None | Abstract |
| `body` | str | Full content of the `.md` file (extracted/converted text) |
| `original_ext` | str \| None | Extension of the companion file (`.pdf`, `.html`, etc.) |

## How a Source is created

1. User calls `POST /zotero/import/{key}`.
2. Server reads the `ZoteroItem` from Zotero (local API or Web API).
3. PDF is fetched (from Zotero attachment or URL).
4. docu-craft converts PDF → `.md` body.
5. `Source` is written to `vault/sources/<slug>.md` with frontmatter.
6. Graphify is marked stale; next cycle indexes the new source.

## Relations

- Originates from a [ZoteroItem](zotero-item.md) (via import).
- Optionally associated with a [Stream](stream.md) via `stream_id`.
- Referenced by [Note](note.md)s and [Chat](chat.md)s via `[[@citekey]]` [Citations](citation.md).
- Indexed by Graphify as a [GraphNode](graph-node.md).

## Relevant axioms

> Sources are immutable. See [Axiom 1](../ontologia.md).
> Every Source has a `.md`; the companion is optional. See [Axiom 10](../ontologia.md).
> Every Source has a `zotero_key`. See [Axiom 11](../ontologia.md).
