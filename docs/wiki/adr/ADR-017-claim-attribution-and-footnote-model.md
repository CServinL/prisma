# ADR-017: Claim Attribution & Footnote Model for Chat

**Date:** 2026-07-27
**Author:** CServinL
**Status:** Implemented (2026-07-31, `faithfulness_checked` added 2026-08-03) —
data model, ontology (Axiom 16, `docs/concepts/footnote.md`), `ChatAgent`
self-segmentation/self-report, `ChatToolbox._graph_context` wiring, UI
rendering, and automated `faithfulness_checked` verification are all built.

### Implementation notes (added 2026-07-31, not part of the original decision)

- The self-report mechanism reuses ADR-014's tool-marker convention rather
  than inventing something new: the model writes `[^N]` inline at each
  claim, then a single trailing `FOOTNOTES_JSON: [...]` line with each
  marker's `relation`/`sources`. Parsing is defensive throughout (bad JSON,
  an unknown `relation`, or a missing line all degrade to "no footnotes,"
  never break the turn) — a self-report is inherently less reliable than a
  tool-call marker, since nothing forces the model to emit it correctly.
- `GraphQueryResult` gained a `sources: list[str]` field so `relational`
  footnotes have real data to draw from — the underlying per-document
  `source_file`s already existed inside `KnowledgeGraphService.query()`,
  they were just being flattened into prose text and discarded before
  reaching the caller.
- UI content is split into text/marker segments and rendered without
  `{@html}`, even for the model's own final reply — consistent with this
  codebase already treating tool results as untrusted content
  (`services/injection_defense.py`).

### `faithfulness_checked` implementation notes (added 2026-08-03)

- **Trigger: automatic, every turn** (user decision) — every footnote with
  a non-empty `sources` list gets a verification call right after
  `_extract_footnotes`, not gated behind a UI action. Accepted cost: on the
  shared compute pool (ADR-014/016), a turn with N sourced footnotes makes
  N additional sequential LLM calls before the turn is considered done.
- `claim_text` (previously always `None` — nothing populated it) is now
  filled deterministically: the sentence immediately preceding each `[^N]`
  marker in the rendered reply (`_extract_claim_texts`), not a model
  self-report. Keeps the self-report JSON minimal (still just
  `index`/`relation`/`sources`), same reasoning as everywhere else in this
  ADR that a self-report is less reliable than something derived from text
  that's already there.
- Verification method: LLM-as-judge, one-shot (`ChatAgent.complete_once`,
  renamed from `summarize` since it now serves two callers — ADR-015's
  Excerpt regeneration and this). Same spirit as `services/dedup.py`'s
  level 4→5 cascade (cheap check first, LLM only when it actually needs
  judgment) — except there's no cheap prefilter for entailment the way
  NLTK stem-overlap works as one for duplicate detection, so every sourced
  footnote gets the LLM call, not just ambiguous ones.
- Source text resolution: `ChatToolbox.get_node_text(slug)`, new — resolves
  a footnote's source slug the same way a wiki-link would (`VaultService.
  get_any`), covering Note/Source body and Chat message transcripts (the
  same past-chat retrieval this session's chat-instructions change made
  explicit in the system prompt). Returns `None` on a missing slug rather
  than raising, so one hallucinated slug doesn't break verification for the
  turn's other footnotes.
- Result stays `None` (not `False`) whenever there's nothing to check:
  `ai-inference` footnotes (no source by design), a `claim_text` that
  failed to extract, an unresolvable source slug, or the verifier LLM call
  itself failing. `None` means "not checked," never conflated with "checked
  and failed."

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
- Required `ChatAgent` to self-segment its own output into per-claim spans
  and self-report `relation`/`sources` at generation time — new prompting
  complexity (built 2026-07-31, see the implementation notes above).
- An LLM can mis-self-report — e.g. label a fabricated/misremembered
  "quote" as `citation` when it isn't one. `faithfulness_checked` (built
  2026-08-03, see its implementation notes above) catches *some* of this —
  an LLM-judge call comparing `claim_text` against the cited source(s) — but
  it's a heuristic, not a guarantee: the judge is itself an LLM call and can
  be wrong, particularly on subtle misrepresentation rather than outright
  contradiction.
- `ChatMessage.sources_cited`'s shape is replaced, not extended — this was
  written assuming there was no live caller to migrate (Chat API routes
  were believed not yet implemented, per `docs/ontologia.md`'s stale "Not
  yet implemented" claim at the time). **Correction, 2026-07-31**: by the
  time this was actually built, `/chat` was live and `ui/src/routes/
  +page.svelte` already had a working chat UI using the old
  `sources_cited: string[]` field name — so there *was* a live caller,
  just not one anyone had gone back to check for. Migrated as part of this
  same implementation pass (`ChatTurn.sources_cited` → `ChatTurn.footnotes`
  in the frontend), not a separate follow-up.

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
