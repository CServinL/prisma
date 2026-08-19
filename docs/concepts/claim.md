# Claim

## What it is

A **Claim** is a per-claim attribution record on a [TurnNode](chat-session-graph.md#node-types)
within a [Chat](chat.md) — a branch node off the turn that asserted it (`ASSERTS` edge), not flat
attached data. Where `Chat`'s grounding (Axiom 5) constrains what context the model may draw
from, a Claim makes visible, per claim, *what kind* of sourcing backs it and *which* document(s)
— mirroring academic citation practice: what is self-made is never left indistinguishable from
what belongs to someone else.

Structurally two different node types, not one class with a variant field (see
[Chat session graph](chat-session-graph.md#node-types) for why the split):

- **`CitedClaimNode`** — traceable to specific vault document(s). Always has `sources` and a
  meaningful `faithfulness_checked`.
- **`InferenceNode`** — the model's own reasoning, traceable to no specific vault document.
  Structurally has neither `sources` nor anything for `faithfulness_checked` to check.

Rendered as a superscript marker inline in the turn's text (`...prior work[^1]`), with a claim
list appended at the end of the turn — one entry per index, each showing its relation/kind and
(for `CitedClaimNode`) the linked [Note](note.md)/[Source](source.md)(s). The inline marker is
clickable (jumps to its list entry) and colored by relation/kind, using the same palette as the
list's badge, so a claim's sourcing is visible where it's actually read, not only after scrolling
to the end.

## Notation

| Rendered | Meaning |
|---|---|
| `...prior work[^1]` | Inline marker — the claim ending here is claim 1, colored by its relation/kind |
| `1. [citation] Smith 2024, "Attention..."` | Claim list entry — relation/kind + linked document (clickable, opens the source) |

## Fields

### `CitedClaimNode`

| Field | Type | Description |
|---|---|---|
| `id` | str | Stable node id (uuid4) — this and every other node type in the session graph got one 2026-08-05 so branches can be referenced without positional fragility |
| `index` | int | Sequential per turn, 1-based — the superscript number shown inline |
| `claim_text` | str | The specific span of the turn's content this claim covers — extracted deterministically (the sentence preceding the `[^N]` marker), not model self-reported. Used as `faithfulness_checked`'s verification input; not separately rendered |
| `sources` | list[str] | Vault node slugs (`Note`/`Source`) this claim ties to |
| `relation` | `citation` \| `paraphrase` \| `attribution` \| `relational` | What kind of sourcing this claim has — see below. Self-reported by the model, then corrected post-hoc by the same LLM-judge call that sets `faithfulness_checked` (single-source claims) or forced structurally (2+ sources always become `relational`) — not purely self-reported |
| `faithfulness_checked` | bool \| None | Whether an automated check confirmed the claim accurately represents the cited source(s): `True`/`False` from an LLM-judge verification call run automatically every turn, `None` when there was nothing to check (no `claim_text`, or an unresolvable source slug). Orthogonal to `relation`, not a relation value itself |
| `qualifier` | `Qualifier` \| None | Toulmin model's epistemic-strength modifier — `certain`\|`probable`\|`possible`\|`tentative` (the last also covers "this is a hypothesis"). Schema only, v3 — nothing populates it yet |
| `warrant` | `WarrantNode` \| None | Toulmin model's Warrant — the reasoning bridge explaining *why* `sources` support this specific claim. `{id, text, backing: list[str]}`; `backing` is Toulmin's Backing (support for the warrant itself), same shape as `sources` since it's the same kind of thing. Schema only, v3 |
| `rebuts` | str \| None | Another `CitedClaimNode`/`InferenceNode`'s `id` this one contradicts or states an exception to (Toulmin's Rebuttal — also covers a self-authored "limitation"). Schema only, v3 |

| `relation` value | Meaning | `sources` |
|---|---|---|
| `citation` | An exact/verbatim quote of a specific passage | exactly one |
| `paraphrase` | A close restatement in different words, same scope as the source | exactly one |
| `attribution` | Broader synthesis/interpretation from one specific document, going beyond a close restatement (e.g. hedged language: "could relate to," "may suggest") | exactly one |
| `relational` | Claim connects or synthesizes across multiple documents (this is what the knowledge graph's `GRAPH_CONTEXT` chat tool inherently produces, and what any 2+-source claim is forced to regardless of self-report) | two or more |

### `InferenceNode`

| Field | Type | Description |
|---|---|---|
| `id` | str | Stable node id (uuid4) |
| `index` | int | Sequential per turn, 1-based, same numbering space as `CitedClaimNode.index` on the same turn |
| `claim_text` | str | The model's own reasoning/generalization this marker covers |
| `qualifier` | `Qualifier` \| None | Same Toulmin field as `CitedClaimNode.qualifier` above. Schema only, v3 |
| `warrant` | `WarrantNode` \| None | Same Toulmin field as `CitedClaimNode.warrant` above — an inference can have a warrant too, even with no `sources` to ground it. Schema only, v3 |
| `rebuts` | str \| None | Same as `CitedClaimNode.rebuts` above. Schema only, v3 |

No `sources`, no `faithfulness_checked` — there's structurally nothing to check or cite. This is
what replaced the old, single-class `Footnote`'s `relation == "ai-inference"` case (see "Relations"
below).

## Relations

- Attached to a `TurnNode` within a [Chat](chat.md) (`TurnNode.claims: list[CitedClaimNode |
  InferenceNode]`) — an `ASSERTS` edge in the [session graph](chat-session-graph.md#edge-types).
- `sources` reference [Note](note.md)/[Source](source.md) slugs — the same vault nodes a
  [Citation](citation.md) or [WikiLink](wiki-link.md) would resolve to — via a `CITES` edge from
  the `CitedClaimNode`, never from `TurnNode` directly.
- `relation == citation` claims are backed by the same resolution mechanism as `Citation`.
- `relation == relational` claims typically originate from `ChatToolbox._graph_context` (the
  knowledge graph query tool), since graph traversal is inherently cross-document.
- Replaces the pre-2026-08-05 `Footnote`/`FootnoteRelation` model (single class, a
  `relation == "ai-inference"` value standing in for what's now `InferenceNode`) — see
  [Chat session graph](chat-session-graph.md#node-types) for why the split.

## Relevant axioms

> Claims are footnoted. See [Axiom 16](../ontologia.md). Distinct from grounding
> (chat-wide context scope, [Axiom 5](../ontologia.md)) and from faithfulness (accuracy of
> representation, tracked per-claim via `faithfulness_checked`, not a `relation` value).

## Build status

Built (2026-07-31): the original single-class `Footnote` data model, `ChatAgent`
self-segmenting its output into per-claim `[^N]` markers and self-reporting `relation`/`sources`
via a trailing `FOOTNOTES_JSON:` line, `relation=relational` sourcing from
`ChatToolbox._graph_context`, and UI rendering.

Built (2026-08-03): `faithfulness_checked` verification — see ADR-017. `claim_text` is extracted
deterministically from the rendered reply (not model self-reported), then every sourced claim is
checked against its cited source(s) via a one-shot LLM-judge call, run automatically after every
turn. This is a heuristic check, not a guarantee: an LLM judge can itself be wrong, so a `True`
doesn't certify accuracy the way a citekey resolving to a real document does — it catches the
common, egregious cases (a claim that plainly contradicts or isn't addressed by its cited
source), not subtle misrepresentation.

Fixed (2026-08-04): footnotes were being computed correctly per-turn but never actually
persisted. Fixed that day via a `<!-- prisma:meta {...} -->` JSON comment per turn; superseded
2026-08-05 when chats moved to pure-JSON `.sess` storage (ADR-019).

Split (2026-08-05, ADR-019): the single `Footnote`/`FootnoteRelation` class replaced by
`CitedClaimNode`/`InferenceNode` (this page) as part of the chat session graph redesign — see
[Chat session graph](chat-session-graph.md#node-types) for the reasoning. `ChatAgent._verify_claim`
(renamed from `_verify_footnote`) and the API/UI all updated to the split shape in the same pass.

Extended (2026-08-17, v3, `CHAT_SCHEMA_VERSION=3`, branch `chat-schema-v3-toulmin-media-
attachments`): `qualifier`/`warrant`/`rebuts` added, covering the remaining four of Toulmin's six
argumentation elements (Claim/Grounds already existed as this class/`sources`) — see
[Chat session graph](chat-session-graph.md#argumentation-structure-toulmin) for the full mapping.
Schema and migration only — nothing in `ChatAgent`'s self-reporting (`_claim_from_raw`,
`FOOTNOTES_JSON:`) produces these fields yet, and the UI renders them only if present (no styling
work needed later once something does populate them).

Split further, and verified (2026-08-18, `CHAT_SCHEMA_VERSION=4`): `citation`'s old merged meaning
("direct quote or close paraphrase") split into `citation` (verbatim quote only) and a new
`paraphrase` value — confirmed live that the model defaults everything to `citation` regardless of
this distinction, so `relation` is no longer purely self-reported. `_verify_claim` (the same call
that already produces `faithfulness_checked`) now also corrects `relation`: a 2+-source claim is
forced to `relational` unconditionally (structural, no LLM judgment needed — `relational` is
definitionally "2+ sources"), and a single-source claim's `citation`/`paraphrase`/`attribution`
choice is corrected by the same fact-checker LLM call, extended to return a second token instead
of firing a separate call. `_migrate_chat_v3_to_v4` is a deliberate no-op — old `relation:
"citation"` data is genuinely ambiguous (quote vs. paraphrase, unrecoverable after the fact) and
is left as-is under the new, narrower meaning rather than reinterpreted.
