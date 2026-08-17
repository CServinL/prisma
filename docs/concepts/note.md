# Note

## What it is

A **Note** is personal, editable content in the vault. It is the intellectual layer — synthesis,
ideas, connections, mind maps, working hypotheses. Notes are what *you* produce; Sources are
what others produced.

Notes are the only vault entity that is routinely written and revised by the user. A Note
can reference [Sources](source.md) via `[[@citekey]]`, embed other nodes via `![[slug]]`,
and link to anything via `[[slug]]`.

## Files on disk

Notes live in `vault/notes/` as `.md` files. They can also carry a companion file alongside the
`.md` — an HTML research output produced by docu-craft (e.g. a sysatlas diagram, a Plotly report),
or (since the v3 chat attachment work, `POST /chats/{slug}/attachments/promote`) a `.jpg`/`.pdf`/
`.svg`/`.tex`/`.drawio` a user attached to a chat and promoted into the vault. `COMPANION_EXTS`
(`prisma/services/vault.py`) is the authoritative recognized-extension list; `.jpg`/`.jpeg`/`.tex`/
`.drawio` were added to it specifically for that promotion path. `original_ext` (below) is how a
loaded `Note` reports which one — if any — actually exists.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier |
| `title` | str | Display name |
| `body` | str | Raw markdown with DSL notation |
| `status` | `NoteStatus` | `draft` \| `active` \| `archived` |
| `excerpt_of_chat` | str \| None | Chat slug if this note is that chat's Excerpt (see [Chat](chat.md#context-management)) |
| `original_ext` | str \| None | Extension of the companion file alongside this Note's `.md` (`.html`, `.jpg`, `.pdf`, `.svg`, `.tex`, `.drawio`, …), `None` if there isn't one. Computed the same way `Source.original_ext` already was (`vault.py`'s `_companion_ext()`) — `get_note()` didn't do this until 2026-08-17, found while building attachment promotion, whose whole point is a servable companion |
| `tags` | list[str] | `#tag` markers |

## Relations

- Cites [Source](source.md)s via `[[@citekey]]` [Citations](citation.md).
- Links to any vault node via `[[slug]]` [WikiLinks](wiki-link.md).
- Can embed other nodes via `![[slug]]` [Transclusions](transclusion.md).
- May be promoted from a [Chat](chat.md) in two distinct senses, not one mechanism: (1) as that
  chat's Excerpt, back-linked via `excerpt_of_chat`; (2) as a plain Note carrying a companion file
  promoted from a chat *attachment* (`POST /chats/{slug}/attachments/promote`, v3) — unrelated to
  `excerpt_of_chat`, not back-linked to the originating chat at all today, see
  [Chat session graph](chat-session-graph.md#attachments-human-turn-input).
- Every `LiteratureReviewReport` is saved as a Note. See [LiteratureReviewReport](literature-review-report.md).
- Indexed as a [GraphNode](graph-node.md).

## Relevant axioms

> Every LiteratureReviewReport becomes a Note. See [Axiom 3](../ontologia.md).
> The knowledge graph indexer re-indexes on save. See [Axiom 8](../ontologia.md).
