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

Status 2026-07-01: `prisma/services/knowledge_graph_service.py` (new module,
`KnowledgeGraphService`) implements all of the below at MVP/deliberately
basic level — schema, per-section extraction, incremental re-extraction,
resource_lock integration, and thin compatibility wrappers
(`ranked_nodes`/`query`/`ollama_deep_search`/`drop_index`/`_ollama_ready`)
matching `GraphifyIndexer`'s public shape so `app.py`'s call sites need no
changes beyond construction. 268 tests passing
(`tests/unit/services/test_knowledge_graph_service.py`).

- [x] **Semantic extraction**: LLM-based entity/relationship extraction from
      `.md` docs/papers → nodes, edges. **Gap not yet closed: images are not
      handled** — the old `DEFAULT_INDEX_EXTENSIONS` included
      `.png/.jpg/.jpeg/.webp/.gif` for vision-model extraction; the new
      module's `_all_md_files()`-based scan only covers `.md`. Separate,
      smaller follow-up, not blocking this cutover. (Code-AST extraction is
      explicitly *not* in scope — unused, vault has no code.)
- [x] **`ranked_nodes(question, top_k)`** — thin wrapper over the new
      module's own basic `search()` (term-match only, no neighbor-expansion
      proximity weighting yet — that refinement is explicitly deferred).
      Used by `/search`'s graph-backed path, no call-site changes needed.
- [x] **`query(question, budget)`** — compact textual summary, simpler than
      Graphify's BFS-token-budgeted graph-context text (just a scored file
      list for now). Used by `ollama_deep_search()`.
- [x] **`ollama_deep_search()`** — merges graph-based file ranking with
      ChromaDB's embedding ranking (max score per file). **Simplification
      vs. the old version: the final LLM-based relevance re-rank step was
      dropped for this MVP** — results are score-merged only, not
      re-ranked by an LLM pass. Still returns ranked results, just with
      less sophistication. Worth adding back once the deferred
      ranked_nodes/surprising_connections work is picked up.
- [x] **Incremental re-extraction** — content-hash-based manifest (simpler
      than Graphify's own semantic cache, given real per-note upsert instead
      of hand-rolled JSON-list merging).
- [x] **GPU/LLM resource-lock integration** — the new extraction module still
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
- [x] **Extraction invocation model — resolved differently than first
      planned, and better.** Originally sized as "subprocess spawned by api,
      stateless, results piped back for api to upsert." Superseded 2026-07-01:
      `KnowledgeGraphService` now runs in its own supervised **process**
      (`kg_app.py`, a 4th worker alongside api/web/chroma), not a
      request-scoped subprocess spawned by api. It owns the sole persistent
      Kùzu connection for that process's entire lifetime and does extraction
      itself — no IPC needed to get nodes/edges back to a separate writer,
      since the process holding the connection *is* the one doing the
      extracting. This gives the same crash isolation Graphify's subprocess
      model had (a wedged/crashed Kùzu call no longer takes api's
      REST/WebSocket traffic down with it) plus more: independent restart,
      and its own CPU core for extraction work instead of competing with
      api's event loop. `app.py` talks to it via `KnowledgeGraphClient`
      (`prisma/services/knowledge_graph_client.py`), a thin HTTP client
      matching `KnowledgeGraphService`'s exact method names — zero further
      call-site changes. Resource-lock holder is `"kg"` now, not `"api"` —
      critical for `release_all_held_by("kg")` to fire correctly if this
      worker crashes/restarts.

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

- [x] Pick Kùzu as the embedded graph store (decided — no server process,
      real Cypher-like traversal, no JVM/ops tax; see the Neo4j vs. Kùzu vs.
      SQLite discussion this file's history was born from).
- [x] **Kùzu concurrency model verified 2026-07-01** (was the top blocking
      question): only one process may hold a database open at all — a
      `READ_WRITE` connection locks out *every* other Database object in any
      other process, including `READ_ONLY` ones (`RuntimeError: Could not
      set lock on file`, confirmed empirically with two local processes, not
      just from docs). Kùzu's own docs recommend an API-server pattern for
      true multi-process access — same lesson ADR-012 already applied to
      ChromaDB.
      **Resolution**: this is not a blocker for prisma's actual architecture
      — only the `api` worker process ever needs graph access (web/chroma
      workers don't touch it). Design: **one persistent `READ_WRITE`
      connection, opened once at `api` process startup, held for the process
      lifetime, closed at shutdown** — no separate supervised Kùzu server
      needed, unlike ChromaDB.
      **Practical consequence worth remembering**: no external tool/script
      can open the graph DB file directly (even read-only) while `prisma
      serve`'s api process is running — it'll hit the same lock error. Any
      inspection/debug tooling must go through the api process's own HTTP
      endpoints, not open the Kùzu file path directly. Don't rediscover this
      the hard way later.
- [ ] Schema: nodes (id, label, file_type, source_file, source_location,
      source_url, captured_at, author, contributor, **trust_tier** —
      source/note/chat, new field not in Graphify's old schema, see the
      "Chat trust tiers" section below) and edges (source, target, relation,
      confidence, confidence_score, weight) — same conceptual shape
      Graphify's JSON used, so migration of the *concept* is straightforward;
      only the storage/query mechanics change.
- [ ] One-time migration path for any existing `graphify-out/graph.json` —
      or accept a cold rebuild, given re-extraction is now cheap and correct
      per-section rather than expensive and sometimes-wrong per-file.

## Chat module (Phase 2 — the actual consumer of all the above)

Design discussion 2026-07-01. **First working increment built 2026-07-02** —
see below for what's actually shipped vs. still sketched.

- [x] **Backend-agnostic LLM interface, built now rather than retrofitted
      later.** Built as `prisma/services/chat_llm.py`'s `ChatLLM` — the
      `openai` SDK against a configurable `base_url`, per ADR-014 (chose
      this over `litellm`/`pydantic-ai` — see that ADR and its appendix for
      the full reasoning, including an empirical tool-calling reliability
      test). Ollama is the only backend today (`chat.provider: ollama` in
      `config.yaml`, its own `ChatConfig` — independent of `llm.model`,
      which stays extraction-only); OpenRouter/Anthropic are additive later,
      OpenRouter needs no new adapter (already OpenAI-compatible), Anthropic
      will. `analysis_agent.py` was deliberately left on its own working
      Ollama-specific code, not retrofitted — per the original note below.
      `compute_pools`' `model_affinity: false` for auto-scaled cloud APIs
      already anticipated this — no rework needed at the resource-lock layer.
- [ ] **Core problem the chat architecture must solve**: local models have
      small context windows (8-16k tokens) — chat cannot feed full files as
      context. Retrieval must hand the model compact representations
      (ChromaDB chunks, graph nodes/edges), not raw documents.
- [x] **Agentic tool-loop, not a fixed single-shot RAG pipeline** (first two
      tools). `prisma/agents/chat_agent.py`'s `ChatAgent.respond()` — the
      model decides what to fetch, rather than the server stuffing one
      prompt upfront:
      - `search_vault(query)` → ChromaDB top-k chunks (built —
        `ChatToolbox._search_vault` in `prisma/services/chat_tools.py`)
      - `graph_context(query)` → `KnowledgeGraphClient.query()` (built —
        `ChatToolbox._graph_context`; not yet the full neighbor-expansion
        sophistication, same deferred scope as ADR-009's follow-up notes)
      - `expand_node(id)` → one-hop graph traversal, on demand — **not
        built yet.** These 5 remaining tools need a real user-facing
        *application*, not just an LLM-callable function — cservinl wants
        this revisited periodically, not treated as a checklist item alone
        (2026-07-02). Worked example given for this one: in the chat UI,
        selecting text and hovering ~1s could trigger a live visualization
        of other vault connections to that selection, using `expand_node`
        directly — a tangible interactive feature, not just a tool the
        model calls on its own initiative.
      - `get_full_text(source_file, section?)` → last resort, deliberate,
        never the default — **not built yet, and reconsidered 2026-07-02**:
        cservinl raised that a flat raw-text dump is the wrong shape given
        the chat model's limited context (`prisma-llm:7b` at 32768, real
        headroom already shared with history/tool round-trips) — source
        access needs to be *delegated*, not inlined. Proposed instead: a
        dedicated **consultation sub-agent** whose only job is to
        map-reduce over one large source's sections (reusing `semchunk`'s
        chunking — same pattern `KnowledgeGraphService._extract_file`
        already uses), asking "does this section help answer {question}"
        per chunk, and returning only the distilled result to the main
        chat loop — not raw text. Meaningful overlap with existing kg
        extraction worth resolving before building this: `graph_context`
        already gives cheap access to what's already been extracted from a
        source; the real gap this fills is going deeper than that when a
        specific source is clearly central and the graph's extracted
        nodes/edges aren't enough. Not just linear map-reduce over one
        document, either — cservinl noted the consultation agent may itself
        need its own tools (`expand_node`, graph DB queries, its own
        semantic search) to actually *follow threads* across the graph
        while consulting a source, not just summarize it in isolation —
        i.e. a nested agent with its own tool loop, not a flat summarizer
        function. Not scoped/built yet — needs its own design pass, not
        bolted on alongside other in-flight chat work.
      - `god_nodes()` / `surprising_connections()` / `suggest_questions()` —
        associative exploration tools (see the framing note above — these
        are retrieval primitives for the model, not user-facing reports)
        — **not built yet.** Same "needs a real application" open question
        as `expand_node` above.
- [x] **Each tool needs a full tool-calling contract, not just an
      implementation.** Built as `ToolSpec` (name, marker, description) in
      `chat_tools.py`, rendered into the system prompt by
      `system_prompt_tool_section()`. Only `search_vault`/`graph_context`
      have specs today; the remaining sketch below is unchanged/not yet built:
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
      - `expand_node(id: str)` / `get_full_text(source_file, section?)` —
        "last resort — only when a specific document is clearly central and
        its full content is genuinely needed. Never call by default."
- [x] **Bounded loop** — `MAX_TOOL_ITERATIONS = 4` in `chat_agent.py`, same
      spirit as Graphify's old `max_retry_depth`, so the agentic loop can't
      quietly burn the shared GPU pool indefinitely.
- [~] **One unified response sanitizer, not three separate passes.** Tool-call
      detection + injection sanitization are built and shared (see below);
      output-truncation handling is still not built (same gap noted
      originally). Decided
      2026-07-01: tool-call *detection* is keyword/pattern-based (the model
      writes a recognizable text pattern, not a native structured
      function-call), because local Ollama models — especially smaller
      quantized ones — don't reliably support/respect native tool-calling
      the way larger cloud models do. That detection lives in the same
      response-processing pass as:
      - **Injection sanitization** — **built and shared**: the
        `<untrusted_source>` wrapping/defanging logic was extracted out of
        `knowledge_graph_service.py` into `prisma/services/injection_defense.py`
        (`wrap_untrusted`/`neutralise_injection_sentinels`) so both the
        knowledge graph's extraction calls and `ChatToolbox`'s tool results
        share one implementation instead of two copies to keep in sync.
        This is the mandatory baseline layer, always on.
      - **Optional second layer (off by default): a small local ML
        injection classifier, scoped only to tool-result content** (never
        user input — see rationale below). Threat model: prisma is
        single-user/local-first, but cservinl *does* want wider adoption —
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

      **Verified empirically, 2026-07-02** (not just assumed): considered
      `pydantic-ai` for the whole agentic tool-loop — its `Agent`/`@tool`
      abstraction maps directly onto the tool-contract design above and
      would remove real hand-rolled loop/schema code. But `pydantic-ai`'s
      tool-calling relies on the model's *native* function-calling protocol,
      with no pattern-based fallback of its own. Ran a disposable 5-prompt
      comparison against `qwen2.5:7b` (the realistic local chat-model
      stand-in, since `llama3.1:8b` isn't actually pulled despite
      `installation.md` naming it default) — native tool-calling (Ollama's
      `/api/chat` `tools` param) vs. a hand-written pattern prompt:
      native got 2/5 clean (picked the *wrong* tool for a clearly relational
      question, and over-triggered a vault search for something the model
      already knew unprompted), pattern-based got 4/5 clean. **Decision:
      skip `pydantic-ai` for now, keep the hand-rolled pattern-based loop**
      — this is a genuine result on the actual candidate model, not just
      inherited caution. Revisit `pydantic-ai` if/when a more capable model
      (larger local model, or a cloud backend once ADR-014 wires one up)
      becomes the default chat backend — cloud models are typically far
      more reliable at native tool-calling, and `pydantic-ai` supports
      custom OpenAI-compatible `base_url`s, so it would compose fine with
      ADR-014's Option B (and its planned Option D migration) if adopted
      later for a backend where native tool-calling actually holds up.
- [x] **All LLM calls the chat loop makes — including every repeated
      tool-loop iteration — go through `resource_lock.lease()`.** Every
      `ChatLLM.complete()` call is lease-gated (holder `"api"`, matching the
      process chat runs in), same as knowledge-graph extraction and
      ChromaDB embedding. Verified live: with the `kg` worker mid-extraction
      (holding `local-ollama`'s `model_affinity` lock on `prisma-llm:7b`), a
      chat request for a *different* model (`qwen2.5:7b`) correctly failed
      open with a graceful "couldn't reach the model" reply rather than
      hanging or crashing — real contention this design anticipated (ADR-012),
      not a bug.
- [x] **Chat persistence** (not originally a checklist item, but needed to
      actually ship anything): transcripts are plain markdown in
      `vault/chats/`, `type: chat` frontmatter (which is *all* that's needed
      for the existing trust-tier machinery — `KnowledgeGraphService._trust_tier_for()`
      already mapped this to `trust_tier: "chat"`, `search()` already excludes
      it — no kg-side changes required). Turns use `### You` / `### Prisma`
      headings (readable in any plain markdown viewer, not just this app);
      tool calls are recorded in-transcript as `> 🔧 used \`tool\`: query`
      lines, not just returned as ephemeral API response data — so tool use
      is visible even when reopening a saved chat later, addressing the
      "show when a tool was used" UX ask directly in the stored format, not
      just the live response. Rendering is plain string-building
      (`VaultService._render_chat_body`/`_parse_chat_body`), not a template
      engine (Jinja2 was considered and rejected — too much machinery for a
      small fixed template) — but still fully `Pydantic`-modeled
      (`ChatMessage`, `ToolCallRecord` in `vault_models.py`), consistent with
      "Pydantic at every turn." **Gap found and fixed along the way**:
      `ChromaIndexer` had no exclusion for `vault/chats/` at all — unlike the
      knowledge graph, ChromaDB's metadata has no `trust_tier` field to
      filter by at query time, so chat transcripts would have leaked into
      `search_vault` results with no way to filter them back out. Fixed in
      both the watcher's exclusion tuple and `_full_index()`'s file list.
- [x] **System prompt is user-editable**, not baked into code or
      `config.yaml`: `prisma/services/chat_prompts.py` materializes
      `~/.config/prisma/chat_system_prompt.md` with a sensible default on
      first use (same bootstrap pattern as `config.yaml` itself), and reads
      it verbatim thereafter.
- [ ] **`/chat` endpoint is single-shot, not streaming** — `POST /chat`
      returns the whole reply once the tool loop finishes; no WebSocket/SSE
      streaming yet, even though ADR-010 already has a WebSocket transport
      for other purposes. Fine for now, worth revisiting once real response
      latency (esp. multi-tool-call turns) makes streaming feel worthwhile
      in the UI.
- [ ] **No UI wired up yet** — `POST /chat` exists and is tested/verified
      live, but `ui/src/routes/` has no chat view/component calling it yet.
      **(In progress 2026-07-02 — see below, this is the current work.)**

### Chat memory model — "meeting, not the meeting notes" (2026-07-02)

**Superseded and built 2026-07-03 — see ADR-015 (Proposed → compressed mode
built).** The N-independent-notes design below turned out to read wrong
once cservinl clarified the intended model: one Excerpt per chat (Summary +
raw pinned copy), not a pile of separate notes, with compressed-vs-verbatim
pinning selected by the chat backend's actual context budget. Left in place
below as the historical record of the first increment; do not extend this
design further.

**Compressed mode built** (verbatim mode — large-context cloud backends —
still not built, no such backend configured yet):
- `Chat.promoted_excerpts`/`pinned_excerpts` (list of independent note
  slugs) replaced with `Chat.pinned_turns: list[int]` (indices into
  `messages`, same identity convention `DELETE .../messages/{index}`
  already used) + `Chat.excerpt_slug: str | None` (the chat's one Excerpt
  note, created lazily on first pin).
- `POST /chats/{slug}/promote` and `POST /chats/{slug}/excerpts/{slug}/pin`
  (old N-notes endpoints) replaced with one
  `POST /chats/{slug}/turns/{index}/pin` (body: `{pinned: bool}`) —
  pin/unpin a turn, which regenerates the chat's single Excerpt note from
  whatever's currently pinned: `ChatAgent.summarize()` (new one-shot
  completion method, bypasses the tool loop) +
  `chat_prompts.load_excerpt_summary_prompt()` (new user-editable prompt,
  same bootstrap-to-`~/.config/prisma/` pattern as the chat system prompt)
  produce the Summary; `VaultService.save_excerpt()` writes Summary + a
  verbatim copy of the pinned turns into one note, reusing it on every
  subsequent pin/unpin rather than creating a new note each time.
- UI: per-turn Pin button is now a real toggle (filled icon when pinned,
  matches current `pinned_turns`), no more "promote to note" dialog asking
  for a title/body — pinning is a single click, title is auto-derived
  server-side. Excerpts panel shows the one Excerpt note directly (Summary
  + raw copy), not a list of independent note cards.
- [x] **Context-usage label** — `ChatAgent.context_usage(history,
      promoted_notes)` returns `(tokens_used, max_tokens)`, reusing the same
      system-prompt/tool-section/Excerpt/bounded-history assembly
      `respond()` sends. `max_tokens` is `max_history_tokens` (the session's
      configured budget), not the backend's raw context ceiling — resolved
      explicitly in ADR-015. Attached to every `Chat` API response (not
      persisted — computed fresh each time) via `app.py`'s
      `_with_context_usage()` helper. UI shows it `k`/`M`-formatted
      (`formatTokenCount()`) next to the model badge, e.g. `1.2k / 16k`.
- [x] **Verbatim mode + the budget-driven mode switch** —
      `ChatConfig.context_window` (new field, defaults to 32768, matching
      `prisma-llm:7b`'s real ceiling) + `ChatAgent.excerpt_mode(pinned_text)`.
      **Real bug caught live and fixed same-session**: the first version
      checked only "is pinned content a small fraction of the window" — but
      a single pinned turn is a small fraction of *any* window, so it put
      even the local 32768-token model into verbatim mode almost
      immediately (observed: pinning one turn never showed a Summary at
      all). Fixed to a two-part check: `context_window` must first clear
      `LARGE_CONTEXT_WINDOW_THRESHOLD` (200,000) before verbatim is even
      considered — today's local model always stays compressed
      unconditionally — and only then does the percentage check
      (`VERBATIM_MODE_MAX_RATIO`, 15%) decide between the two. Verbatim
      mode skips `summarize()` entirely (`save_excerpt(slug, summary=None,
      ...)` omits the "## Summary" heading) — genuinely simpler than
      compressed mode, not just a different code path. Deleting a pinned
      turn (`DELETE /chats/{slug}/messages/{index}`) now re-indexes
      `pinned_turns` and regenerates the Excerpt too — a separate real bug
      the index-based pinning model introduced that didn't exist under the
      old slug-based design, caught and fixed in the same pass
      (`_regenerate_excerpt_now()`, shared between both endpoints). Verbatim
      mode has no practical effect yet — only the local, small-context
      model is configured — but activates automatically once a
      larger-context backend is, no further code changes needed.
- [x] **Real bug fixed same-session, caught live**: `excerpt_mode()`'s first
      version checked only "is pinned content a small fraction of the
      window" — but that's true for almost any small pinned set on *any*
      backend, so it put even the local 32768-token model into verbatim
      mode immediately (cservinl: "I still don't see the summary"). Fixed
      to require the backend's `context_window` itself clear
      `LARGE_CONTEXT_WINDOW_THRESHOLD` (200,000) before verbatim is even
      considered — today's local model now always stays compressed,
      unconditionally.
- [x] **Excerpt regeneration made asynchronous** — `summarize()` is a
      synchronous LLM call that can be slow or fail outright under real GPU
      contention (observed live: a `kg` extraction call timing out at 300s
      on the same shared local model, right as chat tried to regenerate an
      Excerpt). `set_turn_pinned`/`delete_chat_message` now return
      immediately with `pinned_turns` already updated;
      `_regenerate_excerpt_async()` runs the actual summarize+save on a
      background thread, tracked in an in-memory `_excerpt_regenerating`
      registry (not persisted — ephemeral UI status only) surfaced as
      `Chat.excerpt_regenerating`. UI: pinning shows the *previous* Excerpt
      content immediately (never blocks on the LLM call) with a visible
      "regenerating…" spinner in the Excerpts panel header, polling
      `GET /chats/{slug}` every 2s until the flag clears, then refetching.

### Next session: chat responses are too verbose, wasting context budget

cservinl (2026-07-03): the model generates excessively long, example-heavy
answers by default, filling the rolling-history budget (`max_history_tokens`)
much faster than necessary — fewer real turns fit before
`_bounded_history` starts dropping the oldest ones. Needs prompt-level
constraints in `DEFAULT_CHAT_SYSTEM_PROMPT`
(`prisma/services/chat_prompts.py`), something like:
- "Don't generate examples/code samples unless explicitly asked for one."
- Other brevity guidance to discourage padding out answers with
  restated context, redundant elaboration, or unsolicited walkthroughs
  (the kind of output seen filling the context-usage label much faster
  than the actual conversational content would need).

Not scoped/built yet — needs its own pass: figure out the right set of
constraints without making the model unhelpfully terse for questions that
*do* warrant a fuller answer, and verify live rather than guessing (same
discipline as the tool-calling comparison in ADR-014's appendix).

Design discussion after the first increment shipped: cservinl reframed how
a chat's context should be bounded, using a meeting analogy — the initial
prompt is the agenda, the raw back-and-forth is the meeting itself (can be
rolled/pruned freely, not precious on its own), and the actually-valuable
artifact is the "meeting notes" distilled out of it. This directly explains
two fields that already existed in `vault_models.py` unused —
`Chat.promoted_excerpts` and `Note.promoted_from_chat` — they were the
original design intent for exactly this, just never wired up.

- [x] **Bounded rolling history** (the technical safety net) —
      `ChatAgent._bounded_history()`: token-budget-based (reusing the same
      `len(s)//4` heuristic used elsewhere), drops the *oldest* messages
      first once `max_history_tokens` (default 16000, see
      `DEFAULT_MAX_HISTORY_TOKENS`'s comment for the reasoning against
      `prisma-llm:7b`'s real 32768-token ctx) would be exceeded. Silent and
      lossy for the raw transcript's presence in the model's *working*
      context only — never touches what's actually saved to disk
      (`save_chat()` always persists the complete history).
- [x] **Manual curation — delete a specific turn.**
      `DELETE /chats/{slug}/messages/{index}` removes one message and
      resaves. Deliberately not automatic (no AI-driven pruning/summarization)
      — cservinl was explicit that these chats are research media, not
      ephemeral, so *what* gets removed from the working conversation must
      be a human decision, never a model's.
- [x] **Promote to Note — the actual "meeting notes."**
      `POST /chats/{slug}/promote` (body: `title`, `body`, `tags?`) →
      `VaultService.promote_chat_excerpt()` creates a real `Note` with
      `promoted_from_chat: <chat_slug>` in its frontmatter, and appends the
      note's slug to the chat's own `promoted_excerpts`. Always an explicit
      user action (a "assistant proposes, user approves" trigger was
      considered and explicitly deferred — cservinl chose user-only for now).
- [x] **Promoted notes are re-injected as durable context** — the part that
      actually prevents "revisiting already-discussed things" or repeating
      a corrected mistake. `ChatAgent.respond()` takes `promoted_notes:
      list[Note]`, rendered via `_promoted_context_block()` into the system
      prompt as an "already established, don't re-litigate" block —
      deliberately **not** subject to `_bounded_history`'s truncation, since
      the whole point is that this survives even after the raw turns that
      produced it roll away. `/chat` resolves `chat_node.promoted_excerpts`
      slugs to real `Note`s via `_vault.get_note()` before calling
      `respond()`. Verified live end-to-end for create/promote/persist;
      the actual "does the LLM call see it" step is covered by unit tests
      (`test_respond_promoted_notes_survive_history_truncation` etc.) rather
      than a live run — hit real `local-ollama` GPU contention (kg's own
      post-restart full reindex) both times attempted live, same expected
      `model_affinity` behavior already documented elsewhere in this file.
- [ ] **Only promotions from a chat's own history are in scope for now** —
      cross-chat retrieval of promoted notes from *other*, topically-related
      past chats was raised and explicitly deferred: that's really a
      `search_vault`-shaped retrieval problem (notes are already vault
      content, findable that way), not an "always inject" one. Not built.
- [ ] **Consultation sub-agent for large sources — reconsidered scope for
      `get_full_text`.** A flat raw-text dump is the wrong shape given the
      chat model's real, finite context. Proposed instead: a dedicated
      sub-agent that map-reduces over one source's sections (reusing
      `semchunk`, same pattern `KnowledgeGraphService._extract_file` already
      uses) and returns only a distilled answer — and, per cservinl's
      follow-up, this sub-agent may need its *own* tools (`expand_node`,
      graph DB queries, its own semantic search) to actually follow threads
      across the graph while consulting a source, i.e. a nested agent with
      its own tool loop, not a flat summarizer function. Meaningful overlap
      with existing kg extraction to resolve first. Not scoped/built —
      deliberately not bolted on alongside the rest of this session's chat
      work; needs its own design pass.

### Full chat UI (2026-07-02) — built

cservinl was explicit: not a minimal chat box, a *completed* UI. Built into
`ui/src/routes/+page.svelte` (the existing single-file SPA pattern this UI
already uses for notes/sources/streams — no new route/component-library
architecture introduced, stays consistent):

- [x] **Chat list** — sidebar "Chats" section already existed (`loadChats()`
      via `GET /notes?node_type=chat`) but its click handler was wired to
      `openNode()`, which would have broken on a `Chat` (no `.body` field).
      Fixed to `openChat()`. Added a `+` create button (mirrors the Streams
      section's pattern exactly) and right-click rename/delete via the
      existing generic `ctxMenu`/`doRename`/`doDelete` — delete needed no
      new endpoint (`DELETE /nodes/{slug}` already worked generically),
      just extended `doRename`/`doDelete` to also refresh `chats` state.
- [x] **Conversation view** — new `{:else if activeChat}` branch in
      `<main>`, styled turns per role: user turns right-aligned/italic
      ("handwritten" feel), assistant turns left-aligned/monospace ("robot"
      feel, matching the JetBrains Mono already used for technical UI
      elsewhere) — addresses the original styling ask without adding a new
      webfont. Tool-call lines rendered per turn (`🔧 used`, matching the
      persisted markdown convention). Hover-revealed per-turn actions:
      📌 promote, 🗑 delete.
- [x] **Send message** — `sendChatMessage()`, optimistic local append of
      the user's turn, then `POST /chat`, appends the real assistant reply
      + its `tool_calls` on response.
- [x] **Delete a turn** — `deleteChatMessage(index)` →
      `DELETE /chats/{slug}/messages/{index}`.
- [x] **Promote to note** — `startPromote(index)` pre-fills a modal (reused
      the existing `.settings-panel` modal pattern from the stream-creation
      form) with the turn's content as a starting point; user edits
      title/body and confirms → `POST /chats/{slug}/promote`.

Verified: `npm run check` (0 errors/warnings), `npm run build` succeeds,
and the built bundle was grepped directly to confirm the new code is
actually in the served static output — but genuine browser/visual
verification (does it *look* right, does clicking actually feel right)
was **not done** — this environment has no browser-driving tool available.
cservinl should try it live (`prisma serve`, open `/app`) before considering
this truly done.

### Compute-pool model-awareness, real num_ctx correction, model merge (2026-07-02)

Live testing of the UI (indexer running at only ~20-40% GPU utilization)
surfaced that `compute_pools` was under-using real headroom, which led to
several linked fixes:

- [x] **`compute_pools` schema evolved**: `type: gpu|cloud` replaces the
      `model_affinity` boolean (legacy key still read as a fallback), and
      each pool's `models` list can now declare **per-model
      `max_concurrent` overrides** (`{name, max_concurrent}` or a plain
      string for "use the pool default") — different models sharing one
      GPU can have genuinely different safe concurrency ceilings. Also
      used to auto-route a request to the right pool by model name, so a
      cloud model can never accidentally land in a `type: gpu` pool and
      get misattributed as its resident model. See `ResourceManager`
      (`prisma/server/supervisor.py`) and its test suite.
- [x] **Live resource-pool reload**: `POST /supervisor/resources/reload` +
      `prisma reload-resources` CLI command re-read `compute_pools` into a
      *running* supervisor — no restart, no lost in-flight leases. Built
      specifically so tuning `max_concurrent` against observed GPU
      utilization doesn't require killing every worker.
- [x] **`resource_lock.lease()`/`acquire()` gained a `pool` parameter** —
      previously there was no way for a caller to request a *specific*
      named pool at all (a real gap found and dropped earlier when first
      scoping `ChatConfig`, now actually wired end-to-end since the
      `openrouter` pool needs it to stay isolated from `local-ollama`'s
      `model_affinity` serialization).
- [x] **Real correctness bug found and fixed**: `prisma-kg:7b`'s
      `num_ctx=65536` was never actually in effect — Qwen2.5-7B's own
      architecture caps at 32768 tokens, and Ollama silently clamps a
      higher configured `num_ctx` instead of erroring. `ollama show
      --modelfile` only echoes what was configured, not what's enforced;
      `/api/ps`'s loaded `context_length` is the one to trust. See
      ADR-013's follow-up section for the full correction.
- [x] **`prisma-kg:7b` and `prisma-chat:7b` merged into `prisma-llm:7b`** —
      since both were silently running at the same real 32768 context the
      whole time, keeping two identical tags was pure duplication.
      `KnowledgeGraphService.ollama_model` and `ChatConfig.model` both
      default to it now.
- [x] **`OLLAMA_NUM_PARALLEL` bumped 3 → 4** (systemd override,
      `sudo systemctl edit ollama`) after observing real GPU utilization
      had headroom to spare — verified live: 4 genuinely concurrent calls
      to `prisma-llm:7b` at 32768 ctx used only ~7GB VRAM total, ~9GB still
      free of 16GB. `compute_pools.local-ollama.models`'s `prisma-llm:7b`
      entry updated to `max_concurrent: 4` to match — deliberately not set
      higher than Ollama's own real parallelism, since that would just
      mean queueing at the Ollama layer, not actual added concurrency.
- [x] **`OLLAMA_NUM_PARALLEL` systemd override removed entirely** — reverted
      to Ollama's own default (`0`/"auto"), which picks parallel-slot count
      per model from actual free VRAM, same as `OLLAMA_MAX_LOADED_MODELS=0`
      already does for model count. `compute_pools.local-ollama.models`'s
      `prisma-llm:7b` `max_concurrent`/`background_max_concurrent` raised
      (4→6 / 3→5) to stop artificially capping below what the GPU can
      absorb; `vram_budget_mb` + the live `/api/ps` VRAM check are the real
      backstop now, not a static parallelism number. See
      `docs/ollama-concurrency.md`'s follow-up section.
- [x] **Real bug found and fixed while watching live logs**:
      `ChromaIndexer._loop()` cleared `self._pending` *before* attempting
      the embed lease, unconditionally — same class of bug as kg's earlier
      manifest-advance-on-failure issue. Two concrete failure modes fixed:
      1. A file that changed while the embed lease was busy (e.g. kg's own
         long-running extraction holding the shared pool) was silently
         dropped from tracking forever, never retried unless it changed
         again.
      2. **Deletions were needlessly gated behind the same lease** even
         though removing a vector from ChromaDB needs no Ollama call at
         all — a file deleted from the vault while the pool happened to be
         busy would also lose its deletion tracking, for no real reason.
      Fixed by extracting the per-cycle logic into `_process_incremental()`
      (now independently testable), separating deletions (always
      processed) from embeds (lease-gated), and re-queuing only the
      embed-needing files back into `_pending` on denial rather than the
      whole batch. Caught live: a real server log showed Chroma retrying
      for ~10s against kg's long-held lease, then logging "skipped — no
      compute lease available" — the fix means that log line is now
      accurate (it *will* retry next cycle) instead of quietly lying.

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

### Deferred from the correctness self-audit (2026-07-02)

Found while auditing every LLM call site + the Excerpt/pinning data flow +
supervisor concurrency after the kg `num_predict` incident. Critical/medium
items were fixed in the same pass (see `chat_llm.py`, `supervisor.py`,
`vault.py`, `app.py`, `knowledge_graph_service.py`). These are lower-severity
and deliberately deferred rather than fixed blind:

- [ ] `analysis_agent.py::assess_relevance()` logs via `print()` instead of
      the `_log_ollama` logger every sibling method uses — observability
      gap, not a behavior bug.
- [ ] `analysis_agent.py::_relevance_chunk()` fails *open*
      (`[True]*len(candidates)`) on error, while the identity-check methods
      fail *closed* — needs a deliberate sign-off on which failure mode is
      actually wanted here, not a reflexive flip.
- [ ] Timeout values across `analysis_agent.py` are a mix of flat and
      size-scaled — inconsistent in spirit but each individually reasonable;
      revisit as a considered pass, not opportunistically.
- [ ] VRAM-aware resource pool skips the budget check entirely if
      `acquire(..., model=None)` — currently unreachable (every real caller
      always passes `model=`), but a defensive gap for future callers.
- [ ] Stale `pollExcerptRegeneration` interval (ui/src/routes/+page.svelte)
      keeps firing up to one wasted request (~2s) after switching chats
      before self-clearing — harmless, not fixed.
- [x] Excerpt regeneration always overwrites the note body, so a hand-edit
      to the Excerpt note is lost on the next pin/unpin. Decided: document
      as an accepted limitation rather than build edit-detection — the
      Excerpt is meant to be machine-owned, not hand-editable. See
      `docs/wiki/adr/ADR-015-chat-excerpt-context-model.md`. Revisit only if
      this becomes an actual pain point.
