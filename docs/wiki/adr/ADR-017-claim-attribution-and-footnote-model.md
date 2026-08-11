# ADR-017: Claim Attribution & Footnote Model for Chat

**Date:** 2026-07-27
**Author:** CServinL
**Status:** Implemented (2026-07-31, `faithfulness_checked` added 2026-08-03,
persistence + UI interactivity fixed 2026-08-04) — data model, ontology
(Axiom 16, `docs/concepts/claim.md`), `ChatAgent` self-segmentation/self-
report, `ChatToolbox._graph_context` wiring, UI rendering, automated
`faithfulness_checked` verification, and durable per-message persistence are
all built. Rich reply rendering (tables/code/links, 2026-08-04) is built on
the backend (sanitized HTML per message) but not yet wired into the
frontend — see that section below. The single-class `Footnote`/
`FootnoteRelation` model this ADR built was later split into
`CitedClaimNode`/`InferenceNode` (ADR-019, 2026-08-05) — see
`docs/concepts/claim.md`, which documents the current shape; this page is
kept as the historical record of the original decision.

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

### Persistence + UI interactivity fixes (added 2026-08-04)

- **Footnotes were never actually persisted.** `VaultService._render_chat_body`/
  `_parse_chat_body` only ever round-tripped `role`/`content`/`tool_calls` —
  every reload (or server restart) silently reconstructed every historical
  message with `footnotes=[]`, regardless of what a `/chat` response had just
  returned. Found live testing against a real local backend: only the most
  recently sent turn ever showed footnote badges, because that turn's data
  only ever existed in the frontend's in-memory state. Fixed by adding a
  `<!-- prisma:meta {"model": ..., "footnotes": [...]} -->` HTML-comment line
  per turn (invisible in a plain markdown viewer, matching this format's own
  "readable transcript first" intent) — a single JSON blob rather than a
  per-field line like the existing `> used \`tool\`: query` convention,
  since footnotes is a nested list of objects. Parsing is defensive, same
  posture as the model's own FOOTNOTES_JSON self-report: a malformed or
  hand-edited comment degrades to "no metadata for this turn," never breaks
  loading the rest of the chat.
- **`ChatMessage.model`, new field** — the model that actually generated
  that specific message, `None` for user messages. Distinct from `Chat.model`
  (the chat's *current* configured model, silently overwritten on every
  turn per `VaultService.save_chat`'s own docstring) — that field alone
  can't answer "which model produced *this* historical reply" once the
  config changes mid-chat, which matters for comparing model quality across
  a test session (motivating use case: swapping the local backend between
  `qwen2.5-3b` and larger models on the same machine).
- **Inline `[^N]` markers were dead text** — rendered as a bare `<sup>`,
  no click handler, no visual distinction between relation types (only the
  bottom footnote-list badge was colored). Fixed: the inline marker is now
  a button that scrolls to its footnote entry (`#chat-turn-{i}-footnote-{n}`,
  an anchor the list already had) and is colored by `relation` using the
  same palette as the list badge, so a claim's sourcing is visible at the
  point it's actually read, not just after scrolling to the end.
- **`system_prompt_tool_section()`'s tool descriptions now name the actual
  backing system** (`SEARCH_VAULT` → "ChromaDB embedding index", `GRAPH_CONTEXT`
  → "the Knowledge Graph (KG)") instead of only describing behavior — bridges
  the vocabulary the user-editable base prompt already uses ("ChromaDB and
  the knowledge graph") with the code-generated operational instructions,
  since the two were previously written independently and never used matching
  terms for the same systems.

### Rich reply rendering, backend half (added 2026-08-04)

cservinl asked for chat replies to support real markdown — tables, code
blocks, links — instead of rendering as auto-escaped plain text (the
previous, deliberately conservative choice: model-generated text gets the
same caution as tool results, see `injection_defense.py`). `docu_craft`
(the same pipeline Notes/Sources already use via `services/renderer.py`,
Python-Markdown underneath with `tables`/`fenced_code`/`codehilite`/`toc`/
`attr_list`) gives all of that essentially for free — but Python-Markdown
does not sanitize embedded raw HTML by design, and a chat reply is less
trusted than hand-authored Notes (it can echo tool-result/ingested-document
text, an indirect-injection → stored-XSS path if ever rendered unsanitized).

Built:
- `prisma/services/html_sanitize.py` — an `nh3` (maintained Rust binding of
  Mozilla's html5ever/ammonia) allowlist sanitizer. Wired into
  `renderer.render()` itself, so *every* caller gets it automatically —
  this also closes the same latent gap for Notes/Sources, which were
  rendering unsanitized before this.
- `prisma/services/chat_render.py` — converts `[^N]` footnote markers to a
  real `<span class="footnote-marker" data-footnote-index="N">` *before*
  handing content to `renderer.render()`, so the marker survives as actual
  markup the UI can attach click-to-jump/color-by-relation behavior to
  (rather than a fragile client-side string-surgery pass on
  already-rendered HTML, which risks corrupting tag structure if a marker
  lands mid-block).
- `ChatMessage.html: str | None` (new field, API-response-only like
  `Chat.context_tokens_used` — never persisted) and `ChatResponse.html` —
  populated for every assistant message in `POST /chat` and
  `GET /chats/{slug}`.

**Not yet built**: the frontend still renders via the old plain-text
`renderContentSegments()` path (see `+page.svelte`) instead of `{@html}` +
a click-delegate action for the new `.footnote-marker` spans (the existing
`contentClickDelegate` action, already used for Note/Source `{@html}`
content, is the pattern to extend). Needs live browser verification before
landing — held back deliberately rather than shipped un-tested.

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
- `docs/concepts/claim.md` — the entity-level documentation (current shape; this ADR's original `Footnote` class was later split, see the Status line above).
- ADR-009 — hybrid retrieval architecture; `relational` footnotes are the
  natural label for `GRAPH_CONTEXT` tool output.
- ADR-014 — Chat module's LLM backend interface (whatever backend eventually
  does the per-claim self-segmentation runs through this same interface).
- ADR-015 — Chat excerpt & context model (a separate, already-settled Chat
  concern; footnotes are additive to it, not a replacement for anything it
  defines).
