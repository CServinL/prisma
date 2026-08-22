# ADR-021: Vault Node Identifiers — Slug, Path, and Serialized Compound Slug

**Date:** 2026-08-22
**Author:** CServinL
**Status:** Implemented

## Context

`slug` (a bare filename stem, e.g. `nuextract-test-attention`) is the identifier used
throughout the vault: `[[wiki-links]]`, the REST API's `/notes/{slug}`, chat claim
`sources: list[str]`, and the UI's `activeNode.slug`. It deliberately carries no folder
context — this matches Obsidian's own wiki-link convention (`[[name]]`, short and
human-typeable), which the vault's whole design already follows.

The gap: two files in different folders can share a stem, and nothing about `slug` alone
tells them apart. This wasn't hypothetical — a real duplicate surfaced live 2026-08-22:
`notes/nuextract-test-attention.md` and `sources/nuextract-test-attention.md` existed
simultaneously (root-caused separately to a sync-broadcast bug, see the `move_node`/
`rename_node`/`delete_node` fix the same day), both carrying the identical bare slug, with
no way for the UI's "Copy slug" button or a person reading it to tell which was which.

## Decision

Three distinct identifiers now exist, each for a different job — `slug` itself is
unchanged, the other two are additive:

1. **`slug`** — bare filename stem. Wiki-link identity (`[[name]]`), matches Obsidian
   convention. Not guaranteed unique vault-wide; collisions are possible and, per above,
   have happened.
2. **`path`** — vault-relative POSIX path (e.g. `sources/nuextract-test-attention.md`), a
   new field on `RenderedNode` (`prisma/storage/models/vault_models.py`). Read-only,
   disambiguation-only. Never the absolute filesystem path — that would leak local disk
   layout and isn't portable between the server and any client.
3. **Serialized compound slug** — `dir--dir--name` (e.g. `sources--nuextract-test-attention`),
   built by joining `path`'s directory with `slug` using `--` as the separator. This is the
   *same* encoding `move_node()` has produced server-side since ADR's original tree design
   (`str(rel.with_suffix("")).replace("/", "--")`) — not a new scheme, just a second place
   that now produces and consumes it. The UI's "Copy slug" button copies this form instead
   of the bare `slug`, so what actually ends up on the clipboard is disambiguating.

## What resolves a compound slug, and what doesn't

`find_file()` (`prisma/services/vault.py`) already had a `--`-decode branch, but it only
ever tried `.html`. Extended to try `.md` first, then `.html` — since `slug_exists()` (used
by `renderer.py`'s `_resolve_wikilinks`) calls `find_file()` too, a compound slug is now
also a **valid `[[wiki-link]]` target**, not just a copy/paste convenience. This is strictly
additive: the existing bare-stem branch is untouched, so every `[[existing-link]]` already
in the vault keeps resolving exactly as it did before this change.

Not every vault content type supports either link form — this table is the complete,
honest picture, not an implied "everything works":

| Format | Bare-slug link (`[[name]]`) | Serialized link (`[[dir--name]]`) |
|---|---|---|
| `.md` (notes/sources) | yes (existing) | yes (new, this ADR) |
| `.html` (+ companion `.md`) | yes (existing) | yes (existing, unchanged) |
| `.sess` (chats) | n/a — chats were never part of `find_file()`/wiki-link resolution; `_find_sess()` is a separate lookup used only by chat-specific routes | n/a, same reason |
| `streams/*.yaml` | n/a — resolved via `find_stream_path()`, a separate lookup, not `find_file()` | n/a, same reason |

Chats and streams aren't a gap introduced here — they were already outside wiki-link scope
by design before this change.

## What was deliberately not done

- **`slug` itself was not changed to include the path.** The alternative (make every slug
  path-qualified globally) was considered and rejected — it would change the stable
  identity of every existing node vault-wide (routing, wiki-links, chat claim citations,
  bookmarks), a far bigger blast radius for a problem the additive serialized-slug form
  already solves.
- **`VaultTreeNode`** (the sidebar tree's own node shape) was not given a `path` field.
  The sidebar tree-walk already reconstructs each row's directory-relative path client-side
  while rendering (`+page.svelte`'s tree snippet), so per-row disambiguation is derivable
  there without a backend change if ever needed — out of scope for this pass, which only
  covers the node toolbar and the "Copy slug" action.

## Consequences

### Positive
- "Copy slug" now copies something that's actually useful to paste elsewhere — it
  identifies one specific file, not an ambiguous name.
- The node toolbar shows the containing folder next to the title, so the ambiguity is
  visible without needing to copy anything.
- No backward-compatibility cost: every existing `slug` reference (URLs, wiki-links, chat
  claim sources, bookmarks) keeps meaning exactly what it already meant.

### Negative
- Two valid ways now exist to link to the same `.md`/`.html` file (`[[name]]` and
  `[[dir--name]]`) — a minor surface-area increase or `find_file()` to reason about, though
  the decode order (bare-stem first via `_find_md`, then the `--`-decode branch) keeps the
  behavior deterministic.
- The serialized form isn't sanitized character-by-character the way `_file_slug()`
  sanitizes a bare stem — a folder name with spaces or accented characters produces an
  uglier (but still round-trippable) compound slug. Not addressed here; `move_node()` never
  sanitized its own output either, so this isn't a regression, just an existing rough edge
  inherited by the new copy-slug path too.

## Related

- `move_node()`/`rename_node()`/`delete_node()` (`prisma/services/vault.py`,
  `prisma/server/app.py`) — the sync-broadcast fix landing the same day this ADR was written,
  which is what actually produced the live duplicate that motivated this change.
