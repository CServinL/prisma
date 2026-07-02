# Note

## What it is

A **Note** is personal, editable content in the vault. It is the intellectual layer — synthesis,
ideas, connections, mind maps, working hypotheses. Notes are what *you* produce; Sources are
what others produced.

Notes are the only vault entity that is routinely written and revised by the user. A Note
can reference [Sources](source.md) via `[[@citekey]]`, embed other nodes via `![[slug]]`,
and link to anything via `[[slug]]`.

## Files on disk

Notes live in `vault/notes/` as `.md` files. They can also be HTML documents — research outputs
produced by docu-craft (e.g. a sysatlas diagram, a Plotly report). In that case a companion
`.html` file exists alongside the `.md` stub.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier |
| `title` | str | Display name |
| `body` | str | Raw markdown with DSL notation |
| `status` | `NoteStatus` | `draft` \| `active` \| `archived` |
| `promoted_from_chat` | str \| None | Chat slug if this note was promoted from a chat excerpt |
| `tags` | list[str] | `#tag` markers |

## Relations

- Cites [Source](source.md)s via `[[@citekey]]` [Citations](citation.md).
- Links to any vault node via `[[slug]]` [WikiLinks](wiki-link.md).
- Can embed other nodes via `![[slug]]` [Transclusions](transclusion.md).
- May be promoted from a [Chat](chat.md) (back-linked via `promoted_from_chat`).
- Every `LiteratureReviewReport` is saved as a Note. See [LiteratureReviewReport](literature-review-report.md).
- Indexed as a [GraphNode](graph-node.md).

## Relevant axioms

> Every LiteratureReviewReport becomes a Note. See [Axiom 3](../ontologia.md).
> The knowledge graph indexer re-indexes on save. See [Axiom 8](../ontologia.md).
