# Claim / Toulmin (`chat_agent.py`) review checklist

Distilled from ~9 Copilot review rounds on PR #105 (populating `qualifier`/`warrant`/`rebuts`
from the model's `FOOTNOTES_JSON` self-report). Each round found a real defect in the same
~40-line area (`_RawFootnote`, `_resolve_rebuts`, the rebuts jump-link) — a pattern of the same
class recurring at nearby lines, not isolated one-offs.

**Run this list against any change to `_RawFootnote`/`_claim_from_raw`/`_resolve_rebuts`
(`chat_agent.py`), `system_prompt_footnote_section()` (`chat_tools.py`), or the claim-rendering
block in `+page.svelte` — and against the change's siblings, not just the line being touched.**

## 1. A referential id must resolve against the *final* surviving set, not a pre-drop snapshot

`_resolve_rebuts` used to build `by_index` once, up front, from every parsed entry — including
ones about to be dropped for their own reasons (an invalid index, or later in `respond()` an
unresolvable `sources`/`warrant.backing` slug). A claim could resolve its `rebuts` to a target's
real `id` while that target was still valid, then have the target vanish anyway, leaving a
dangling reference `session_graph.py`'s `REBUTS` edge would silently turn into a phantom,
data-less node (NetworkX auto-creates any edge endpoint that isn't already a node).

Any code that resolves one entry's reference against a sibling entry in the same batch must
either resolve *after* all drops are final, or re-validate (`_prune_dangling_rebuts`'s
fixed-point loop) after every subsequent filtering pass that can still remove the target —
including passes owned by a different function that has no visibility into the first one's work.

## 2. Strict-type a self-report field to what the format actually promises — type *and* range

`rebuts`/`index` were plain `int`: Pydantic's lax mode coerced `true`→`1` and `1.0`→`1`, so a
malformed self-report built a real, "valid-looking" edge/marker instead of being rejected.
`StrictInt` closed that, but `0`/negative values are still strictly-typed `int`s — the documented
format is 1-based `[^N]`, so `index` also needed `Field(gt=0)`. **Fixing the type-coercion half is
not the whole fix if the field's format promises a narrower value range than "any int."**

`rebuts` deliberately has no `gt=0` of its own: an out-of-range `rebuts` value can never match a
real (now-guaranteed-positive) `index`, so it's already correctly rejected by the "no such index"
path — don't add a redundant constraint just for symmetry when a different existing check already
covers the failure mode.

## 3. A uniqueness assumption a new feature relies on must be validated, not assumed

`by_index = {c.index: c for c, _ in built}` silently picked the last claim when two entries shared
an `index` — and the UI's `id="chat-turn-N-claim-{index}"` DOM anchor collides the same way
(invalid duplicate ids; the browser picks whichever it wants). `rebuts` didn't rely on index
uniqueness before this feature — once it does, duplicate indices become a live correctness bug,
not just cosmetic. Every claim sharing an ambiguous key is dropped up front, before anything gets
built that's keyed by it — not "pick one arbitrarily" and not "only reject the reference to it."

## 4. Every parser-side constraint needs a producer-side (prompt) contract update

`_RawWarrant.backing` got a hard `max_length` cap (`MAX_WARRANT_BACKING`) with nothing in
`system_prompt_footnote_section()` telling the model the ceiling exists — a model that (correctly,
per the instruction it *was* given: "only real slugs you actually saw") cited 21 real sources got
its entire otherwise-valid claim silently dropped. **A `Field(max_length=...)`/`gt=...`/enum
constraint added to a self-report model is only half the fix; the prompt text the model actually
reads must state the same number/range.** `MAX_WARRANT_BACKING` lives in `chat_tools.py` (the
producer's home), imported by `chat_agent.py` (the parser) — not the other way around, since
`chat_agent.py` already imports `chat_tools.py` for `FOOTNOTES_LINE_RE`/`TOOL_CALL_RE`/`TOOLS`, and
the reverse direction would be circular.

## 5. A feature's intentionally-narrow *input* scope must not silently become the *render* scope

The model's self-report can only produce a same-turn `rebuts` (`_resolve_rebuts` is deliberately
same-turn-only — the self-report has no other handle). But `CitedClaimNode.rebuts`/
`InferenceNode.rebuts` is an **unrestricted claim id** at the schema level, and
`session_graph.py`'s `REBUTS` edge already supports a cross-turn target
(`tests/unit/agents/test_session_graph.py` has one). The UI's `rebuts` jump-link built its
id→index lookup from one turn's `msg.claims` only — inheriting the new producer's narrowness for
free, with no error, just a missing button for any cross-turn rebuts that exists (from any
source, present or future). **Render against what the schema/other producers support, not just
what today's newest producer emits** — here, a chat-wide `id -> {turn, index}` map.

## 6. Updating a field's lifecycle status means updating *every* source of truth for it

Concept docs (`claim.md`, `chat-session-graph.md`) got updated to say Toulmin fields are
populated — but the *inline docstrings on the schema fields themselves*
(`vault_models.py`'s `WarrantNode`/`CitedClaimNode` comments) still said "schema support only,
nothing populates this yet," directly contradicting the concept docs a reader might not even
check. The same repo-wide sweep this triggered found the identical staleness pattern, independent
of this PR, in: `TurnNode`'s `media`/`attachments` comment (attachments *are* populated;
`media`/`PRODUCES` genuinely isn't — the old comment blanket-labeled both), `chat.md`'s `thoughts`
field and Toulmin row (both said "nothing populates this yet" when `thoughts` shipped
2026-08-18), the `ThinkingNode`/`InlineMediaNode`/`AssetMediaNode`/edge-type rows in
`chat-session-graph.md`'s own node/edge table (still said "on branch (unmerged)" for a PR merged
weeks earlier — a table contradicting that same doc's own dated Status section below it), and
`docs/wiki/roadmap.md` (top-level "Not yet merged" for a whole feature set that had long since
shipped). **A "schema only / nothing populates this yet" claim is a standing liability the moment
it's written — when the gap it describes closes, grep for the phrase across the repo, not just in
the file you're editing**, and check it field-by-field (a struct can have some fields populated
and others still dormant; don't blanket-label the whole thing either way).
