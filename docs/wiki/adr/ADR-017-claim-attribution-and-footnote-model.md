# ADR-017: Claim Attribution & Footnote Model for Chat

**Date:** 2026-07-27
**Author:** CServinL
**Status:** Proposed — data model built (`Footnote`/`FootnoteRelation` in
`storage/models/vault_models.py`), ontology settled (Axiom 16,
`docs/concepts/footnote.md`). `ChatAgent` does not yet segment its own
output into per-claim spans or self-report `relation`/`sources` at
generation time — see `TODO.md`'s "Chat claim attribution / footnotes"
section for the remaining implementation checklist.

## Context

cservinl raised a concern with how Chat responses (see `docs/concepts/chat.md`,
Axiom 5 — "Chats are grounded") actually read: a response can be entirely
grounded (context scoped to vault nodes only, no external retrieval) and
still blend the model's own synthesis/inference with claims that trace to a
specific document into one seamless-sounding paragraph, with no way for the
reader to tell which is which. Framed directly: "in science, articles are
written so that what is self-made is not confused with what belongs to
others, references are given to this." Existing grounding (Axiom 5)
constrains *input scope* — it says nothing about whether the *output text*
marks, per claim, where each assertion came from. The only existing
mechanism, `ChatMessage.sources_cited: list[str]`, is a flat, message-level
list of citekeys — it doesn't say *which* claim within the message ties to
*which* source, or distinguish a direct quote from a loose paraphrase from
the model's own unsupported reasoning.

### Terminology considered

Several existing terms were weighed for naming this, since they're easy to
conflate:

| Term | What it actually answers | Verdict |
|---|---|---|
| **Grounding** | Is the model even allowed to use knowledge beyond what it was given? (input scope) | Already used for Axiom 5 — a different axis, kept as-is, not overloaded |
| **Faithfulness** | Does the claim accurately represent what the source says? (accuracy) | Real, but orthogonal — a claim can be attributed yet unfaithful, or vice versa. Modeled as a QA flag (`faithfulness_checked`), not a relation type |
| **Provenance** | Where did this data come from, mechanically, through a pipeline? | Too broad/pipeline-level, not specific to per-claim text marking |
| **Evidentiality** | Linguistic category marking a claim's source-type (firsthand/inferred/reported) | Conceptually close to the right idea, but a linguistics term — wrong register for this documentation; kept the underlying distinction, used plainer labels |
| **Attribution (AIS — Attributable to Identified Sources; Rashkin et al., Google Research, 2021)** | Can this claim be traced to and verified against a specific source? | **Adopted** — this is the standard NLP/RAG-research term for exactly the problem described |

## Decision

A new entity, **`Footnote`**, attached per-message rather than per-chat:
`ChatMessage.footnotes: list[Footnote]` (replacing `sources_cited`, which had
no consumers in code yet — a clean rename, not a breaking change to any
live caller).

```python
class FootnoteRelation(str, Enum):
    citation = "citation"          # direct quote / close paraphrase, one document
    attribution = "attribution"    # paraphrased/synthesized from one document
    relational = "relational"      # connects/synthesizes across multiple documents
    ai_inference = "ai-inference"  # model's own reasoning, no vault source

class Footnote(BaseModel):
    index: int                          # 1-based, sequential per message — the superscript shown inline
    relation: FootnoteRelation
    sources: list[str] = []             # Note/Source slugs; empty only for ai_inference
    claim_text: str | None = None       # span of ChatMessage.content this covers
    faithfulness_checked: bool | None = None  # orthogonal QA flag, see below
```

### Rendering

Inline superscript marker in `ChatMessage.content` (`word¹`), with a footnote
list appended at the end of the assistant's turn — one entry per index,
showing `relation` and the linked `Note`/`Source`(s). Standard academic
footnote convention: **footnote reference** (the superscript callout in the
body text) → **footnote** (the corresponding entry at the end, giving the
actual source).

### Why four relation values, not more or fewer

- `citation` and `attribution` both resolve to exactly one document — the
  distinction is verbatim-quote vs. paraphrase, which matters for how
  confidently a reader can trust the wording itself vs. just the underlying
  claim.
- `relational` maps directly onto what the knowledge graph's `GRAPH_CONTEXT`
  chat tool (`services/chat_tools.py::ChatToolbox._graph_context`) already
  produces — graph traversal is inherently cross-document, so this wasn't
  invented for symmetry, it reflects a retrieval path that already exists
  (see ADR-009).
- `ai_inference` is the explicit "self-made" bucket — required so that the
  *absence* of a source is a first-class, visible state rather than a
  silently-blended gap. A response that is mostly `ai_inference` footnotes
  is meaningfully different from one that's mostly `citation`/`attribution`,
  and that difference should be inspectable.
- `faithfulness_checked` was deliberately **not** made a fifth relation
  value — faithfulness is a correctness check *on top of* an already-sourced
  claim (did the model represent `sources` accurately), not a sourcing
  *type*. An `ai_inference` claim has no source to be faithful to, so
  folding faithfulness into the relation enum would produce a nonsensical
  combination.

## Consequences

### Positive
- Makes the "self-made vs. belongs-to-others" distinction inspectable per
  claim, not just an input-side promise (Axiom 5) the output text has no
  obligation to honor legibly.
- Reuses existing resolution machinery — `sources` are the same `Note`/
  `Source` slugs `Citation`/`WikiLink` already resolve, so no new lookup
  mechanism is needed, just a typed wrapper around it.
- `relational` gives the KG retrieval layer (ADR-009) a first-class label in
  chat output, rather than its cross-document results being flattened into
  the same bucket as single-document paraphrases.
- Enables a future trust/QA metric: what fraction of a chat's footnotes are
  `ai_inference` vs. sourced, and how many sourced claims have
  `faithfulness_checked == True`.

### Negative
- Requires `ChatAgent` to self-segment its own output into per-claim spans
  and self-report `relation`/`sources` at generation time — new prompting
  complexity, not yet designed or built (see `TODO.md`).
- An LLM can mis-self-report — e.g. label a fabricated/misremembered
  "quote" as `citation` when it isn't one. This ADR does not solve that.
  `faithfulness_checked` is the intended (currently unbuilt) hook for
  eventually catching it — a real, harder, separately-deferred problem, not
  a guarantee this design provides today.
- `ChatMessage.sources_cited`'s shape is replaced, not extended — acceptable
  here since Chat API routes aren't implemented yet (per `docs/ontologia.md`'s
  "Not yet implemented" section), so there is no live caller to migrate.

## Related

- Axiom 5 (`docs/ontologia.md`) — grounding (input scope), the axis this
  explicitly does not overload.
- Axiom 16 (`docs/ontologia.md`) — the axiom this ADR implements.
- `docs/concepts/footnote.md` — the entity-level documentation.
- ADR-009 — hybrid retrieval architecture; `relational` footnotes are the
  natural label for `GRAPH_CONTEXT` tool output.
- ADR-014 — Chat module's LLM backend interface (whatever backend eventually
  does the per-claim self-segmentation runs through this same interface).
- ADR-015 — Chat excerpt & context model (a separate, already-settled Chat
  concern; footnotes are additive to it, not a replacement for anything it
  defines).
