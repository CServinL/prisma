# Footnote

## What it is

A **Footnote** is a per-claim attribution record on an assistant turn in a [Chat](chat.md).
Where `Chat`'s grounding (Axiom 5) constrains what context the model may draw from, a Footnote
makes visible, per claim, *what kind* of sourcing backs it and *which* document(s) — mirroring
academic citation practice: what is self-made is never left indistinguishable from what
belongs to someone else.

Rendered as a superscript marker inline in the turn's text (`word¹`), with a footnote list
appended at the end of the turn — one entry per index, each showing its `relation` and the
linked [Note](note.md)/[Source](source.md)(s).

## Notation

| Rendered | Meaning |
|---|---|
| `...prior work¹` | Superscript marker — the claim ending here has footnote 1 |
| `1. [citation] Smith 2024, "Attention..."` | Footnote list entry — relation type + linked document |

## Fields

| Field | Type | Description |
|---|---|---|
| `index` | int | Sequential per message, 1-based — the superscript number shown inline |
| `relation` | `FootnoteRelation` | What kind of sourcing this claim has — see below |
| `sources` | list[str] | Vault node slugs (`Note`/`Source`) this claim ties to. Empty only when `relation == ai-inference` |
| `claim_text` | str \| None | The specific span of `content` this footnote covers — extracted deterministically (the sentence preceding the `[^N]` marker), not model self-reported. Used as `faithfulness_checked`'s verification input; not separately rendered |
| `faithfulness_checked` | bool \| None | Whether an automated check confirmed the claim accurately represents the cited source(s): `True`/`False` from an LLM-judge verification call run automatically every turn, `None` when there was nothing to check (`ai-inference`, no `claim_text`, or an unresolvable source slug). Only meaningful when `sources` is non-empty — orthogonal to `relation`, not a relation type itself |

### FootnoteRelation

| Value | Meaning | `sources` |
|---|---|---|
| `citation` | Direct quote or close paraphrase of a specific passage | exactly one |
| `attribution` | Synthesized/paraphrased from one specific document, not verbatim | exactly one |
| `relational` | Claim connects or synthesizes across multiple documents (this is what the knowledge graph's `GRAPH_CONTEXT` chat tool inherently produces) | two or more |
| `ai-inference` | The model's own reasoning/generalization, traceable to no specific vault document | none |

## Relations

- Attached to a `ChatMessage` within a [Chat](chat.md) (`ChatMessage.footnotes`).
- `sources` reference [Note](note.md)/[Source](source.md) slugs — the same vault nodes a
  [Citation](citation.md) or [WikiLink](wiki-link.md) would resolve to.
- `relation == citation` footnotes are backed by the same resolution mechanism as `Citation`.
- `relation == relational` footnotes typically originate from `ChatToolbox._graph_context`
  (the knowledge graph query tool), since graph traversal is inherently cross-document.

## Relevant axioms

> Claims are footnoted. See [Axiom 16](../ontologia.md). Distinct from grounding
> (chat-wide context scope, [Axiom 5](../ontologia.md)) and from faithfulness (accuracy of
> representation, tracked per-footnote via `faithfulness_checked`, not a `relation` value).

## Build status

Built (2026-07-31): the data model, `ChatAgent` self-segmenting its output into per-claim `[^N]`
markers and self-reporting `relation`/`sources` via a trailing `FOOTNOTES_JSON:` line,
`relation=relational` sourcing from `ChatToolbox._graph_context`, and UI rendering.

Built (2026-08-03): `faithfulness_checked` verification — see ADR-017. `claim_text` is extracted
deterministically from the rendered reply (not model self-reported), then every sourced footnote
is checked against its cited source(s) via a one-shot LLM-judge call
(`ChatAgent._verify_footnote`), run automatically after every turn. This is a heuristic check,
not a guarantee: an LLM judge can itself be wrong, so a `True` doesn't certify accuracy the way a
citekey resolving to a real document does — it catches the common, egregious cases (a claim that
plainly contradicts or isn't addressed by its cited source), not subtle misrepresentation.
