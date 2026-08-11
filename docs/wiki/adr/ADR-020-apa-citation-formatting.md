# ADR-020: APA Citation Formatting

**Date:** 2026-08-05
**Author:** CServinL
**Status:** Proposed — design drafted, not built. Several open questions
(marked below) need cservinl's decision before implementation starts.
Deliberately deferred out of the ADR-019 session-graph work (task tracking:
"Add APA citation formatting for claims") — a separate formatting concern
layered on top of [Claim](../../concepts/claim.md)'s existing
`CitedClaimNode.sources: list[str]` resolution, not a change to that model.

## Context

Every [Claim](../../concepts/claim.md) (`CitedClaimNode`) already carries `sources: list[str]` —
vault slugs, never free text, enforced today at the system-prompt level
(`system_prompt_footnote_section()`, `chat_tools.py`): "Only cite documents you actually saw...
their exact slug... Never invent a slug." The UI renders each source as a clickable button that
opens the vault node (`claim-source-link` in `+page.svelte`) — a slug, not a formatted citation.
cservinl's ask: render these (and citations elsewhere in the vault) as real APA-formatted
references, with the machinery to go both directions between a slug and its APA string.

## Findings from this planning pass (grounded in the actual code, not assumed)

1. **`Source` doesn't carry enough metadata for a correct APA citation today.**
   (`prisma/storage/models/vault_models.py:92-106`) — `Source` has `citekey`, `authors: list[str]`,
   `year`, `doi`, `abstract`, `body`, but no `journal`/`publication_title`, `volume`, `issue`,
   `pages`, `publisher`, `url`, or `item_type` (article vs. book vs. web — APA's format differs by
   type). A correct APA journal-article citation needs at minimum
   `Author, A. A. (Year). Title. Journal Name, Volume(Issue), pages.` — today's `Source` can only
   ever produce `Author, A. A. (Year). Title.`, missing everything after the year for anything
   beyond the simplest case.
2. **The missing data already exists at import time and is thrown away.** `ZoteroItem`
   (`prisma/storage/models/zotero_models.py:126-`) has `publication_title`, `volume`, `issue`,
   `pages`, `date`, `doi`, `url`, `item_type`, `creators` — everything APA needs. The import route
   (`zotero_routes.py:200-226`) only ever uses `publication_title`/`authors`/`doi`/`url` to build
   *unstructured prose* in `body` (and only when there's no PDF to convert instead — a PDF-backed
   import gets none of this, not even as prose). `volume`/`issue`/`pages`/`item_type` are never
   used at all. `create_source_from_citekey()` (`vault.py:482`) doesn't accept them as parameters,
   so there's no structured field for them to land in even if the call site passed them.
3. **`url` is a live, silent-drop bug, independent of APA.** `create_source_from_citekey()` writes
   `fm["url"] = url` into the source's frontmatter (`vault.py:495-496`), but `Source` has no `url`
   field and `get_source()` (`vault.py:456-479`) never reads `fm.get("url")` back out — every
   imported source's URL is persisted to disk and then silently discarded on every subsequent load.
   Worth fixing regardless of APA, but directly blocks APA formatting for web sources (`item_type`
   webpage citations are URL-anchored).
4. **Referencing-to-slug is already enforced, but only at the prompt level, not in code.**
   `CitedClaimNode.sources` has no Pydantic validator confirming each slug resolves to a real vault
   node — the only existing safety net is `_verify_claim`'s faithfulness check noting
   `faithfulness_checked = None` for "an unresolvable source slug" (soft signal, not a rejection).
   The `[[@citekey]]` DSL ([Citation](../../concepts/citation.md)) has its own, separate resolution
   path (`resolved: bool`, broken citations surface in `RenderedNode.broken_citations`) — exact
   citekey match, unrelated machinery from `CitedClaimNode.sources`. cservinl's first bullet
   ("verify that we enforce referencing, to slug") is asking whether `CitedClaimNode.sources`
   should get the same hard-validation treatment `[[@citekey]]` already has, not building it from
   scratch.
5. **Text-based slug lookup already exists (`SEARCH_VAULT`, `/search/deep`); APA-based lookup does
   not.** Nothing today takes an APA-formatted string and resolves it back to a `Source` slug —
   the reverse of the "slug → APA" direction, not just a variant of the existing semantic search
   (matching a citation string's specific structure, not general semantic similarity).

## Proposed phases

1. **Extend `Source` with the missing bibliographic fields**: `journal: str | None`,
   `volume: str | None`, `issue: str | None`, `pages: str | None`, `publisher: str | None`,
   `url: str | None` (fixes finding 3 as a side effect), `item_type: str | None` (APA template
   selector — journal article / book / webpage / etc.). Thread these through
   `create_source_from_citekey()`, `get_source()`'s frontmatter read, and the Zotero import call
   site (`zotero_routes.py`) from `ZoteroItem`'s already-fetched fields (finding 2) — no new
   external data, just stop discarding what's already there.
2. **`utils/source_metadata.py` (or similar) — a completeness evaluator.** Given a `Source`,
   return which fields are missing for a *correct* APA citation of its specific `item_type` (a
   journal article's requirements differ from a book's or a webpage's) — not just "does it have
   authors and a year." Used by both phase 3's converter (to degrade gracefully — omit
   volume/issue rather than crash when absent) and a vault-health view flagging under-cited
   sources.
3. **Slug → APA converter** — a pure function, `Source` (+ its completeness evaluation) in,
   an APA 7th-edition-formatted string out, `item_type`-aware templates. Where it lives (new
   `citation_format.py` service module vs. a `Source` method) is an implementation-time call.
4. **APA → Slug converter (reverse lookup)** — inherently fuzzy, unlike `[[@citekey]]`'s exact
   match: parse (author surname, year) at minimum out of an arbitrary APA-shaped string, narrow
   candidates by `Source.authors`/`Source.year`, disambiguate by title similarity when multiple
   sources share an author+year. Needs its own tests around malformed/partial input — this is the
   "APA-based slug finder" finding 5 identified as missing.
5. **APA validator** — checks a string actually conforms to APA structural rules (regex/structural,
   not semantic). Two uses: self-check phase 3's own output in tests, and reject-early on garbage
   input to phase 4's parser before attempting extraction.
6. **Whether/how metadata carries a cached APA string** — see open question 2 below; if resolved
   toward caching, this phase writes the rendered string into frontmatter (`fm["apa"] = ...`)
   at the same points phase 1's fields get written/edited.
7. **System-prompt instruction** — see open question 3 below; blocked on resolving what the model
   is actually being asked to change, since today it never writes citation text at all (only
   `[^N]` markers + slugs — APA rendering already happens entirely server/UI-side per
   [Claim](../../concepts/claim.md)'s existing rendering model).

## Open questions (need cservinl's decision before implementation)

1. **Hard-validate `CitedClaimNode.sources` against real vault slugs?** (finding 4) A Pydantic
   validator or construction-time check would turn today's soft "faithfulness_checked degrades to
   None" signal into an actual rejection/error — more correct, but changes failure behavior
   (`ChatAgent` would need a defined response to a model citing a slug that doesn't exist, beyond
   today's silent degrade).
2. **Cached APA string in frontmatter, or always computed on demand?** cservinl's ask ("slug
   metadata containing its APA representation") points at caching, but the codebase's existing
   precedent for derived text (`RichContent.rendered_html`) is compute-fresh-on-every-read, not
   cache-at-rest, specifically to avoid staleness drift when the source data changes. If cached,
   needs a defined regeneration trigger (every `save_source`? explicit re-render command?) so a
   hand-edited `journal`/`year` in frontmatter can't leave a stale cached APA string behind.
3. **What does "instruct the model to use APA in references" actually change?** The model doesn't
   generate reference text today — it emits `[^N]` markers plus a `sources: [slug]` list; APA
   rendering (once built) would happen entirely at claim-list render time (server/UI), not in the
   model's own output. Possible actual intents, needing cservinl to pick one: (a) nothing changes
   about what the model does, this bullet is actually about the renderer, already covered by
   phases 1-3; (b) the model's *inline prose* should start citing in APA in-text style (e.g. "...as
   shown by (Smith, 2024)...") in addition to or instead of the `[^N]` marker convention — a real
   UX change to how claims read, not just how the reference list at the bottom is formatted.
4. **Backfill for existing sources** — phase 1's new fields are only populated going forward
   (new Zotero imports). Existing vault sources imported before this lands have no
   `journal`/`volume`/`issue`/`pages`/`url`/`item_type` on file. Needs either a one-time backfill
   command (re-fetch from Zotero's API by `zotero_key`, already stored on every `Source`) or
   acceptance that pre-existing sources render degraded (author/year/title-only) APA citations
   until re-imported.

## Related

- [Claim](../../concepts/claim.md) — `CitedClaimNode.sources` is what this ADR formats; not
  changed in shape by this work, only rendered differently.
- [Citation](../../concepts/citation.md) — the `[[@citekey]]` DSL's existing exact-match
  resolution is the precedent open question 1 is asking whether to extend to claims.
- [ADR-017](ADR-017-claim-attribution-and-footnote-model.md) /
  [ADR-019](ADR-019-persisted-format-governance-and-migrations.md) — where `CitedClaimNode` and
  its `sources` field came from.
