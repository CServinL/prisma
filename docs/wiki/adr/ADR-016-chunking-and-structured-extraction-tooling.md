# ADR-016: Chunking and Structured-Extraction Tooling

**Date:** 2026-07-04
**Author:** CServinL
**Status:** Accepted

## Context

While investigating a live incident (kg extraction running for ~12 hours,
root cause: `_call_ollama_extract` had no `num_predict` cap), the codebase's
LLM/RAG stack got compared against a list of adjacent tools — Chonkie,
Marker, Langfuse, Qdrant, Ollama, DSPy, Crawl4AI, Outlines, LiteLLM,
Instructor. Two real, non-speculative gaps came out of that comparison,
verified against the actual code (three parallel read-only Explore agents)
and, for the two libraries actually adopted, verified live (scratch venvs,
`pip install` + direct API inspection, not assumed from memory). This ADR
records both decisions plus the rest of the survey's verdicts, so the list
doesn't need re-litigating later.

## Decision 1: Chunking — `semchunk`, not Chonkie

`chroma_service.py::_chunk_markdown` reimplemented chunking from scratch —
a regex heading split (`re.split(r"(?m)^#{1,2} ", text)`) plus blind
character-count slicing, no token-awareness, no overlap. Meanwhile
`knowledge_graph_service.py` already used `semchunk` for the same job,
token-budget-aware. Two chunking strategies for the same kind of content in
one codebase, one of them (chroma's) markedly worse — a standing convention
violation ("we have semchunk for that, no homebrewed chunkers"), not a
deliberate design choice.

**Chonkie** was the obvious library-swap candidate raised alongside this.
Verified live (`pip install chonkie` in a scratch venv, `dir(chonkie)`
inspected directly, not assumed from its README): it has grown into a full
RAG-pipeline framework — vector-DB "Handshakes" (`ChromaHandshake`,
`QdrantHandshake`, etc.), embeddings wrappers (`OpenAIEmbeddings`,
`JinaEmbeddings`, ...), LLM wrappers ("Genies" — `OpenAIGenie`,
`GeminiGenie`, ...), and document-parsing "Chefs" (`MarkdownChef`,
`MistralOCR`) — not a focused chunking library anymore. Adopting it just
for chunking would mean depending on a framework that duplicates `ChatLLM`,
`_embed_texts`, and Marker/docu-craft-adjacent document parsing, all
unused.

**Decision: `semchunk`.** Already a dependency, already the established
in-repo pattern (kg's extraction path), and does exactly the one job
needed — token-budget-aware splitting via a supplied token-count callable,
with the same `len(s)//4` heuristic kg already uses. `chroma_service.py`'s
`_chunk_markdown` now calls it directly, replacing the regex/slice logic
entirely.

## Decision 2: Structured LLM output — Instructor, not Outlines

`knowledge_graph_service.py`'s `_call_ollama_extract` (extraction call) +
`_parse_extraction_response` (parsing) hand-parsed JSON with a
markdown-fence-stripping regex and manual `.get()` defaulting on bare
dicts — no Pydantic model for the `{"nodes": [...], "edges": [...]}` shape
at all. This had a confirmed, tested, recurring failure mode: the model
wraps output in ` ```json ` fences on longer inputs despite `format:
"json"` and an explicit system-prompt instruction not to (confirmed
empirically: wrapped responses every time at ~8k/~11k input tokens vs.
clean output at ~1.2k tokens for equivalent content) — silently discarding
a perfectly good extraction as "found nothing," not a sign of degrading
entity recall.

Two libraries directly address this: **Instructor** (client-side,
Pydantic-validated `response_model=`, retries on validation failure) and
**Outlines** (grammar-constrained decoding — the inference server itself
guarantees schema-conformant tokens).

**Decision: Instructor.** Verified live (`pip install instructor` in a
scratch venv, `instructor.from_openai(OpenAI(base_url=f"{base_url}/v1",
api_key="ollama"), mode=instructor.Mode.JSON)` inspected directly):
`.chat.completions.create(response_model=..., max_retries=3, **kwargs)`
validates against a Pydantic model and retries client-side on failure,
raising `instructor.core.exceptions.InstructorError` if retries are
exhausted. `Mode.JSON` (not the default `Mode.TOOLS`) was chosen
deliberately: it matches the existing `format: "json"` approach and avoids
native tool-calling — ADR-014's own tool-calling reliability test already
found native tool-calling unreliable for this local model class
(qwen2.5:7b: 2/5 clean vs. 4/5 for a pattern-based approach), so JSON mode
is the consistent choice here too.

Outlines was not chosen because it requires grammar-constrained decoding
support on the Ollama/inference side — it hands control of the generation
process to the grammar engine rather than the calling code. Instructor
keeps validation/retry control client-side, consistent with how every
other LLM call site in this codebase already works (`ChatLLM`'s own
`openai`-SDK-based design, ADR-014's Option B). Both were genuine options
addressing a real, tested gap — this was a "which one" decision, not a
"do we need this at all" one.

**Implementation:** `Node`/`Edge`/`Extraction` Pydantic models now mirror
the prompt's old inline JSON schema example (which was removed from the
system prompt — redundant once `response_model=` enforces the shape
structurally). `_call_ollama_extract` still gates every call through the
same `self._extraction_semaphore` and `resource_lock.lease(...)` as
before — unchanged, since that's what arbitrates GPU concurrency — but
calls the Instructor-wrapped client instead of raw `requests.post`.
Instructor's retries happen *inside* the lease, since each retry is a real
Ollama call. `_parse_extraction_response` and its fence-stripping regex are
deleted — dead code once Instructor owns parsing and validation.

## Rejected outright

- **LiteLLM** — already covered by ADR-014: `ChatLLM` gives backend-agnostic
  calls via the `openai` SDK's `base_url` trick, and ADR-014 explicitly
  rejected LiteLLM for that interface. The real duplication that exists
  (kg, `analysis_agent.py`, and `chroma_service.py` each hand-rolling their
  own Ollama-native HTTP calls) is about using Ollama-specific features
  (`format: "json"`, `/api/embed`) LiteLLM doesn't change — not a
  multi-provider gap.
- **Langfuse** — prisma is local-only, single-user, Ollama has no
  per-token billing; Langfuse's core value (cross-provider cost tracking,
  team trace sharing) doesn't apply. The actual observability gap
  (`analysis_agent.py::assess_relevance()` still using bare `print()`
  instead of the `_log_ollama` logger every sibling method uses) is a
  one-line fix to the existing logger, not a reason to add an external
  service.
- **Qdrant** — no stated Chroma pain point anywhere in `TODO.md` or prior
  ADRs. ADR-012 already solved the actual problem (crash isolation, via
  `chroma run` as its own supervised subprocess) that would motivate a
  vector-DB swap; this was never a performance/scale complaint.

## Deferred, not rejected

- **Crawl4AI** — a genuinely new capability, not a replacement for
  something homebrewed: prisma has zero raw-HTML/web-crawling capability
  today (ingestion is Zotero-API-only; `search_agent.py`'s Academia.edu
  path explicitly stubs out HTML parsing). Flagged specifically for the
  research-stream pipeline (`research_stream_manager.py`, which drives
  `search_agent.py`'s arxiv/semanticscholar-only discovery) — extending
  stream discovery to sites without a clean API is a real, separate
  product-scope decision. Tracked in `TODO.md`.
- **DSPy** — not surveyed this round at all (out of scope for the 3
  Explore agents launched). Genuinely unassessed, not a "no" — worth a
  look if prompt-optimization becomes a priority for `analysis_agent.py`'s
  KEY:value-parsing prompts or kg's extraction prompt. Tracked in
  `TODO.md`.
- **Marker** — a docu-craft concern (PDF → markdown extraction), not a
  prisma one; already logged in `docu-craft/TODO.md`'s "Analyze the use of
  Marker" entry.

## Consequences

### Positive
- `chroma_service.py` and `knowledge_graph_service.py` now share one
  chunking approach (`semchunk`) instead of two, one of which was
  materially worse (char-based, no overlap, mid-word slicing).
- kg extraction gets real schema validation and retry-on-invalid instead
  of a regex workaround for a known, recurring failure mode — should
  reduce silent "found nothing" extractions caused by fence-wrapped
  responses.
- Both decisions keep the dependency footprint minimal and consistent with
  this codebase's existing preferences (ADR-003, ADR-014): `semchunk` is
  tiny and already present; Instructor adds one focused dependency without
  pulling in unrelated provider/vector-DB/embedding integrations the way
  Chonkie or LiteLLM would.

### Negative
- Instructor's retry-on-validation-failure means a single section's
  extraction can now make up to `max_retries` (3) real Ollama calls instead
  of always exactly one — slightly more GPU time per failing section, held
  under the same lease. Bounded and consistent with the existing
  semaphore/lease gating, not unbounded.
- `_call_ollama_extract` now depends on Ollama's OpenAI-compatible
  `/v1/chat/completions` endpoint instead of its native `/api/generate` —
  a different HTTP surface than before, though already proven in this
  codebase via `ChatLLM` (ADR-014).

## Related ADRs

- ADR-013: Native Knowledge Graph — the extraction path this ADR changes.
- ADR-014: Chat Module's LLM Backend Interface — the LiteLLM rejection
  this ADR references rather than re-litigates, and the tool-calling
  reliability test whose result informed the `Mode.JSON` choice here.

## Citation

Instructor requests citation for academic/research use — appropriate here,
since prisma is itself a literature-review tool:

```bibtex
@software{liu2024instructor,
  author = {Jason Liu and Contributors},
  title = {Instructor: A library for structured outputs from large language models},
  url = {https://github.com/instructor-ai/instructor},
  year = {2024},
  month = {3}
}
```
