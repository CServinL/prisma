# TODO: Replace Graphify with a native, Kùzu-backed knowledge graph module

See `docs/wiki/roadmap.md` (Phase 2) for the high-level decision and rationale.
This file is the working checklist.

## Why

- `graph.json` is a flat JSON blob: every query reparses the whole file into
  networkx in memory, there's no incremental upsert, and merging graphs from
  separate extraction runs means hand-rolling JSON-list concatenation.
- Graphify's per-file chunking bottoms out at "one whole file" — a single
  document that alone exceeds the model's token budget has no further
  recovery path (`_extract_with_adaptive_retry`'s "single-file chunk ...
  cannot be split further" case) and silently returns a truncated,
  incomplete extraction on every run, forever. Confirmed live with
  `Cunningham_2023_SAEs_Interpretable_Features.md`.
- Prisma never used most of Graphify's surface: no code-AST extraction (the
  vault has no code files), no git hooks, no IDE skill installers. What's
  actually exercised is narrow enough to own directly.

## What prisma actually uses today (must keep working)

- [ ] **Semantic extraction**: LLM-based entity/relationship extraction from
      `.md` docs/papers and images → nodes, edges, hyperedges. (Code-AST
      extraction is explicitly *not* in scope — unused, vault has no code.)
- [ ] **`ranked_nodes(question, top_k)`** (`graphify_service.py`) — term-match
      + one-hop neighbor-expansion, ranks source files by relevance. Used by
      `/search`'s graph-backed path.
- [ ] **`query(question, budget)`** — compact textual summary of the most
      relevant graph neighborhood, fed as LLM context. Used by
      `ollama_deep_search()`.
- [ ] **`ollama_deep_search()`** — merges graph-based file ranking with
      ChromaDB's embedding ranking (max score per file), asks the LLM for a
      final relevance re-rank. Must keep working against the new backend
      with no behavior change from the caller's perspective.
- [ ] **Incremental re-extraction** — only changed files get re-processed
      (Graphify's own semantic cache did this; the new module needs an
      equivalent, ideally simpler given a real DB with per-note upsert).
- [ ] **GPU/LLM resource-lock integration** — the new extraction module still
      calls Ollama, so it still needs to go through `resource_lock.lease()`
      exactly like Graphify does today (same holder, same `local-ollama`
      pool, same `model_affinity` behavior — see ADR-012).

## New capability (the actual point of the token-budget fix)

- [ ] **Per-section extraction, not per-file** — chunk *within* a large
      document (by heading/section, token-budget-aware — `semchunk` was
      evaluated and is a good fit for this specific slicing step) so no
      single file can ever be "too big to extract." Each section's nodes/
      edges get upserted independently — no whole-document atomicity
      requirement, no bisection-recursion needed.

## Unused Graphify capability we explicitly want to gain (chat module)

Framing: these are not standalone user-facing reports — they're fast,
associative/semantic **context-retrieval primitives for the chat LLM itself**,
the same role `ranked_nodes`/`query` already play in `ollama_deep_search()`.
The goal is giving the model quick means to focus attention and pull in
related material by graph structure, not just by vector similarity — a
different, complementary retrieval signal to hand the LLM alongside
ChromaDB's results, not a display feature for the user to browse directly.

- [ ] **`god_nodes`-equivalent** — surface highly-connected hub entities, so
      chat can pull in "the entities everything else in this area relates
      to" as anchor context, even if the user's question doesn't name them.
- [ ] **`surprising_connections`-equivalent** — surface unusual/unexpected
      cross-domain links, so chat can associatively connect a question to
      material that's structurally relevant but wouldn't rank highly by
      text/embedding similarity alone.
- [ ] **`suggest_questions`-equivalent** — auto-generate questions from graph
      structure, primarily to give chat a way to proactively suggest
      follow-ups grounded in what's actually in the vault, not just to
      display as static conversation starters.

## Chat trust tiers — chats are not sources

Decided 2026-07-01. Chats are exploratory/temporary scratchwork ("a
playground"), never independently citable — unlike `sources/` (external,
authoritative) or `notes/` (the user's own deliberate writing). Concrete
design, not just a prompt-phrasing caveat:

- [ ] **`search_vault` and any general-purpose fact-retrieval tool exclude
      `chats/` by default.** Architectural guarantee, not reliance on the
      model correctly weighing an inline "this is tentative" label — a local
      7B model may not respect that reliably.
- [ ] **A separate, distinctly-named tool for chat recall** —
      e.g. `recall_past_discussion(topic)` — called only when the model
      wants conversational continuity, never blended into fact-retrieval
      results.
- [ ] **Every retrieved snippet still carries an explicit trust-tier label**
      in its framing regardless of tool (`[SOURCE — citable]` vs.
      `[PAST DISCUSSION — exploratory, not verified]`) — defense-in-depth on
      top of the above, not instead of it.
- [ ] **New schema field: `trust_tier`** (source/note/chat), distinct from
      `file_type` (which already means paper/code/document/image) — on every
      graph node/edge and every ChromaDB entry, so it's queryable/filterable,
      not just a prompt-time label.
- [ ] **Deletion cascade**: deleting a chat vault item must remove its
      ChromaDB embeddings (existing delete path already handles this for any
      vault file) *and*, once the graph store exists, any nodes/edges
      extracted from that chat.

### Deferred: user-fact extraction from chat (not now — noted for later)

Gemini-style pattern: extract small, durable *user-stated facts* from chat
(e.g. "lives in Aguascalientes," "interested in starting a carwash
business") into their own curated memory, separate from the raw transcript.
This is a different case from the self-citation risk above — safe
specifically because the user is the authoritative source for facts about
*themselves*, unlike citing the model's own past inference as if it were
external fact. Likely its own trust tier (arguably higher than "chat" for
self-facts specifically, since the user is ground truth here) — design when
actually picked up, not now.

## Storage

- [ ] Pick Kùzu as the embedded graph store (decided — no server process,
      real Cypher-like traversal, no JVM/ops tax; see the Neo4j vs. Kùzu vs.
      SQLite discussion this file's history was born from).
- [ ] Schema: nodes (id, label, file_type, source_file, source_location,
      source_url, captured_at, author, contributor) and edges (source,
      target, relation, confidence, confidence_score, weight) — same shape
      Graphify's JSON used, so migration of the *concept* is straightforward;
      only the storage/query mechanics change.
- [ ] One-time migration path for any existing `graphify-out/graph.json` —
      or accept a cold rebuild, given re-extraction is now cheap and correct
      per-section rather than expensive and sometimes-wrong per-file.

## Chat module (Phase 2 — the actual consumer of all the above)

Design discussion 2026-07-01. Not started; capturing the architecture before
it's lost.

- [ ] **Backend-agnostic LLM interface, built now rather than retrofitted
      later.** Prisma's design intent is cross-backend (Ollama first, then
      OpenRouter, then Anthropic API — per the user, not yet in any code
      today). `analysis_agent.py` currently hardcodes Ollama's
      `/api/generate` directly; the chat module should NOT repeat that
      pattern. One thin interface, Ollama as the only implementation
      initially, so later backends are additive. Decide separately (later,
      not blocking) whether to retrofit `analysis_agent.py` onto the same
      interface or leave its working Ollama-specific code alone.
      `compute_pools`' `model_affinity: false` for auto-scaled cloud APIs
      already anticipated this — no rework needed at the resource-lock layer.
- [ ] **Core problem the chat architecture must solve**: local models have
      small context windows (8-16k tokens) — chat cannot feed full files as
      context. Retrieval must hand the model compact representations
      (ChromaDB chunks, graph nodes/edges), not raw documents.
- [ ] **Agentic tool-loop, not a fixed single-shot RAG pipeline.** The chat
      LLM gets callable tools and decides what to fetch, rather than the
      server stuffing one prompt upfront:
      - `search_vault(query)` → ChromaDB top-k chunks
      - `graph_context(query|node)` → Kùzu neighbor-expansion /
        `ranked_nodes`-equivalent
      - `expand_node(id)` → one-hop graph traversal, on demand
      - `get_full_text(source_file, section?)` → last resort, deliberate,
        never the default
      - `god_nodes()` / `surprising_connections()` / `suggest_questions()` —
        associative exploration tools (see the framing note above — these
        are retrieval primitives for the model, not user-facing reports)
- [ ] **Each tool needs a full tool-calling contract, not just an
      implementation** — a Python function alone isn't usable by the model.
      Per tool: name, parameter JSON schema, a description that states *when*
      to call it (not just what it does), and a documented return shape the
      model can reliably parse. Sketch (to refine when actually built):
      - `search_vault(query: str)` — "default first step for almost any
        question." Returns `[{text, source_file, score}]`.
      - `graph_context(query: str)` / `expand_node(id: str)` — "call when the
        question is about how things relate, or vector search results seem
        scattered/incomplete." Returns `[{entity, relation, related_entity,
        source_file}]`.
      - `god_nodes()` — "call for broad/orienting questions with no specific
        narrow target, e.g. 'what are the big themes in my notes about X',
        or to orient before diving into specifics." Returns ranked
        `[{entity, connection_count, sample_relations}]`.
      - `surprising_connections()` — "call when the user explicitly asks for
        unexpected/creative connections, or when direct search results seem
        too narrow/obvious for what's being asked." Returns
        `[{node_a, node_b, relation, why_surprising}]`.
      - `suggest_questions()` — "call to propose grounded follow-ups at the
        end of an answer, or when the user seems stuck / asks what to
        explore next." Returns `[{question, grounding_source_file}]`.
      - `get_full_text(source_file, section?)` — "last resort — only when a
        specific document is clearly central and its full content is
        genuinely needed. Never call by default." Returns raw text (still
        `semchunk`-bounded to fit the remaining context budget).
- [ ] **Bounded loop** — cap tool-call iterations per turn (same shape as
      Graphify's `max_retry_depth`), so the agentic loop can't quietly burn
      the shared GPU pool indefinitely.
- [ ] **One unified response sanitizer, not three separate passes.** Decided
      2026-07-01: tool-call *detection* is keyword/pattern-based (the model
      writes a recognizable text pattern, not a native structured
      function-call), because local Ollama models — especially smaller
      quantized ones — don't reliably support/respect native tool-calling
      the way larger cloud models do. That detection lives in the same
      response-processing pass as:
      - **Injection sanitization** — any vault content returned by a tool
        needs the same untrusted-content wrapping Graphify's
        `<untrusted_source>` handling does today (regex-stripping injected
        closing tags etc.) — worth directly adapting that approach. This is
        the mandatory baseline layer, always on.
      - **Optional second layer (off by default): a small local ML
        injection classifier, scoped only to tool-result content** (never
        user input — see rationale below). Threat model: prisma is
        single-user/local-first, but the user *does* want wider adoption —
        each install is still single-user, so the threat that actually
        matters is indirect injection from unvetted ingested content
        (a downloaded paper/web page crafted to look like instructions once
        it's in the model's context), not adversarial end users or
        multi-tenant compliance (PII/toxicity/language filtering are
        irrelevant here — skip full frameworks like `llm-guard` entirely,
        their bloat (~740MB unquantized ONNX) buys nothing we need). If
        semantic (not just structural) injection detection is wanted later,
        use a small standalone INT8 ONNX DeBERTa classifier directly via
        `onnxruntime` + a tokenizer — no framework:
        `hlyn/prompt-injection-judge-deberta-70m` (~83MB, ~100ms CPU, F1 0.81
        — verified real on Hugging Face 2026-07-01) or
        `protectai/deberta-v3-small-prompt-injection-v2` (same vendor as
        `llm-guard`'s own scanner, likely the more battle-tested/maintained
        option, usable standalone without the framework around it). Keep
        this behind a config toggle, off by default — the mechanical
        delimiter-escaping baseline above is the core defense; this is
        purely defense-in-depth for later, once real ingested content
        volume justifies the extra CPU cost.
        At ~83MB, CPU-only, this doesn't need `resource_lock`/`model_affinity`
        at all — it never touches the GPU pool or VRAM, so there's no
        contention with Ollama to arbitrate. Load it once, keep it resident
        for the process lifetime (singleton at worker startup, same pattern
        as Graphify's own `_get_tokenizer()`/`_TOKENIZER` cached-at-import
        approach) — no lazy per-call load/unload needed given the size.
      - **Output-truncation handling** — detect a cut-off/hollow model
        response and continue/retry, mirroring Graphify's
        `finish_reason=length` handling. NEW gap: `semchunk` only bounds
        input size; nothing today handles output getting cut off mid-answer,
        including `analysis_agent.py`. Worth generalizing so it could reuse
        this too.
      Tradeoff to keep in mind: keyword/pattern matching is more fragile than
      a real structured tool-call API (ambiguous phrasing, false-positive
      trigger words in normal prose). This is where the backend-agnostic
      interface pays off again: a future cloud backend with solid native
      tool-calling could use that instead, while Ollama uses the
      pattern-based fallback, both behind the same interface.
- [ ] **All LLM calls the chat loop makes — including every repeated
      tool-loop iteration — go through `resource_lock.lease()`.** An agentic
      loop is *more* Ollama traffic per user turn than anything today; no new
      call site should bypass the pool arbitration built this session.

## Cutover

- [ ] New module lives in `prisma/services/` (name TBD — not `graphify_service.py`,
      to avoid confusion with the removed dependency).
- [ ] Remove the `graphify` pip dependency and all `graphify.*` imports.
- [ ] Update all touchpoints found in the survey: `prisma/server/app.py`,
      `prisma/server/supervisor.py`, `prisma/server/web_app.py`,
      `prisma/services/vault.py`, `prisma/services/chroma_service.py`,
      `prisma/storage/local_db.py`, `ui/src/routes/+page.svelte`
      (graphify status widget), plus docs: `docs/wiki/architecture.md`,
      `docs/wiki/features.md`, `docs/wiki/installation.md`,
      `docs/wiki/configuration.md`, `docs/wiki/adr/ADR-009-hybrid-retrieval-architecture.md`,
      `docs/wiki/adr/ADR-012-process-supervision.md`.
- [ ] Update/replace `tests/unit/services/test_graphify_service.py` and the
      graphify-specific parts of `tests/unit/server/test_supervisor_resources.py`.
- [ ] Regenerate diagrams (`docs/diagrams/gen.sh`) once the new module lands.
