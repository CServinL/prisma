# ADR-020: APA Citation Formatting

**Date:** 2026-08-05 (open questions resolved and implemented 2026-08-11)
**Author:** CServinL
**Status:** Implemented, including the chat UI wiring originally left out of
scope. All 4 open questions below resolved 2026-08-11: hard validation (not
soft degrade), compute-fresh-on-read (not cached), no model behavior change
(rendering only), one-time backfill command (not accept-degraded). Phases 1-5
built as scoped; phases 6-7 (cached string, system-prompt instruction) turned
out to be moot once their blocking questions resolved toward "don't cache" /
"no model change" — see each open question below for what actually shipped
instead. `GET /notes/apa?slugs=...` (`notes_routes.py`) + `+page.svelte`
fetching/caching it per slug, rendering each claim's APA citation as an extra
line below its source link, landed same day as a follow-on once cservinl
asked about it directly — not deferred after all. Deliberately deferred out of the
ADR-019 session-graph work (task tracking: "Add APA citation formatting for
claims") — a separate formatting concern layered on top of
[Claim](../../concepts/claim.md)'s existing `CitedClaimNode.sources: list[str]`
resolution, not a change to that model.

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

## Phases (all built 2026-08-11)

1. **Extended `Source`** with `journal`/`volume`/`issue`/`pages`/`publisher`/`url`/`item_type`
   (`vault_models.py`). Threaded through `create_source_from_citekey()`, `get_source()`'s
   frontmatter read, and the Zotero import route (`zotero_routes.py`, from `ZoteroItem`'s already-
   fetched fields including `get_field("publisher")` for the one field with no named `ZoteroItem`
   attribute). Fixed finding 3's `url` silent-drop bug as a side effect.
2. **`prisma/services/citation_format.py`: `missing_fields_for_apa(source)`** — completeness
   evaluator, `item_type`-aware (journal-like/book-like/web-like/generic), used by `format_apa()`
   to degrade gracefully rather than crash on absent fields.
3. **`citation_format.py`: `format_apa(source) -> str`** — the slug → APA converter. Handles
   1/2/3+ author lists (APA's `&`-before-last convention), no-author (title leads instead of a
   repeated title), `n.d.` for a missing year, DOI preferred over a bare URL when both present.
4. **`citation_format.py`: `find_source_by_apa(text, sources) -> list[Source]`** — the reverse
   lookup, confirmed fuzzy as expected: parses a leading surname + year (or `n.d.`) out of `text`,
   filters candidates by both, ranks remaining ties by title word overlap. A real bug caught by its
   own test suite during implementation: the initial `n.d.` handling matched *any* source
   regardless of whether that source itself had no year — fixed to require the candidate's own
   `year is None` too.
5. **`citation_format.py`: `validate_apa_format(text) -> bool`** — structural check (an
   author/title lead-in followed by `(Year).`/`(n.d.).`, the shape `format_apa()` itself always
   produces), not semantic.
6. **Not built — resolved moot.** Open question 2 resolved toward compute-fresh-on-read; there is
   no cached APA string to write or regenerate.
7. **Not built — resolved moot.** Open question 3 resolved toward "no model behavior change";
   `system_prompt_footnote_section()` is untouched by this ADR.

Additionally, resolving open question 1 required a real design call not anticipated by phases
1-5: hard-validating `CitedClaimNode.sources` needs vault I/O, which doesn't belong inside a
Pydantic field validator (no vault access, breaks construction in tests, dependency-free models).
Built instead as `ChatToolbox.slug_resolves(slug) -> bool` + `ChatAgent._sources_resolve(claim)`,
wired into `respond()` right after `_extract_claims()` — a claim citing an unresolvable slug is
now dropped (logged), not just left with `faithfulness_checked = None`. `InferenceNode` trivially
resolves (no sources to check). And resolving open question 4 needed a real write path that didn't
exist: `VaultService.update_source_bibliographic_fields()` (merges into existing frontmatter,
never blanks a field just because a re-fetch didn't return it), plus
`prisma/services/source_backfill.py` + the `prisma backfill-source-metadata` CLI command
(dry-run by default, `--apply` to write, mirroring `migrate-chats-to-sess`'s existing UX) —
skips sources with no `zotero_key` or already-populated fields, re-fetches the rest via
`ZoteroClient.get_item()`.

## Open questions — all resolved 2026-08-11

1. **Hard-validate `CitedClaimNode.sources` against real vault slugs?** → **Yes, hard-validate.**
   See phase list above for where this actually landed (not a Pydantic validator).
2. **Cached APA string in frontmatter, or always computed on demand?** → **Compute fresh on read.**
   Matches `RichContent.rendered_html`'s existing precedent; no staleness-drift risk, and
   `format_apa()` is cheap enough (`missing_fields_for_apa()` + string formatting only, both
   pure/no I/O) that caching would have been optimizing something that was never slow.
3. **What does "instruct the model to use APA in references" actually change?** → **Nothing about
   the model.** Resolved as (a) from the original options — `system_prompt_footnote_section()` is
   untouched; APA rendering is purely a `format_apa()` call at claim-list render time, same
   rendering model [Claim](../../concepts/claim.md) already had.
4. **Backfill for existing sources** → **One-time backfill command**, not accept-degraded. See
   phase list above.

## Related

- [Claim](../../concepts/claim.md) — `CitedClaimNode.sources` is what this ADR formats; not
  changed in shape by this work, only rendered differently.
- [Citation](../../concepts/citation.md) — the `[[@citekey]]` DSL's existing exact-match
  resolution was the precedent for hard-validating `CitedClaimNode.sources` too (open question 1).
- [ADR-017](ADR-017-claim-attribution-and-footnote-model.md) /
  [ADR-019](ADR-019-persisted-format-governance-and-migrations.md) — where `CitedClaimNode` and
  its `sources` field came from.
