# Chat session graph

## What it is

How a [Chat](chat.md) represents its own internal structure — not another vault node type, the
actual shape of what's inside `Chat.messages` since ADR-019's 2026-08-05 v2 schema. Before this,
a `Chat` was a flat `messages: list[ChatMessage]`, each carrying a flat `tool_calls` *summary*
(name + args, no result) and, since turn regeneration, an `alternates` list. Two things were
missing: intermediate tool-call results and reasoning steps were never persisted at all (they
existed only transiently inside `ChatAgent.respond()`'s tool loop, for the one completion call
that produced them), and there was no general way to ask "what produced this turn" beyond the
one special-cased `alternates` field.

The session graph reframes a chat as a **main line of `User <-> AI` turns, with everything else
— tool calls, reasoning steps, past regeneration attempts — as branches off that line**, not
competing with it for position in a flat list. This is what makes selective context loading
possible: the [`SessionOrchestrator`](#sessionorchestrator) walks the main line for free and only
follows a branch edge when a turn actually needs it, instead of "everything within a token
budget, oldest-first" (the pre-ADR-019 fixed formula) or "everything pre-compressed into one
Summary" (the [Excerpt](chat.md), [ADR-015](../wiki/adr/ADR-015-chat-excerpt-context-model.md)).

Not a rename of the [knowledge graph](graph-node.md) — that graph connects vault-wide *content*
(entities/relationships extracted from Notes/Sources across the whole vault, queried via
`GRAPH_CONTEXT`). This graph is scoped to *one chat session's own internal flow* — one graph per
`.sess` file — but `RECALL` (below) is not: since 2026-08-05 it also searches a bounded set of
*other* chats' graphs, each rebuilt the same way, at a discounted weight (see
[`RECALL`'s resolved behavior](#recalls-resolved-behavior)). A chat's `CITES` edges point *into*
the knowledge graph's vault nodes, but the session graph(s) and the knowledge graph remain
otherwise independent structures serving different questions — cross-chat `RECALL` still never
touches Kùzu, it's several of *this* graph shape, not a step toward the vault-wide one.

## Node types

Every node type below has a stable `id: str` (uuid4, assigned at creation, immutable) — positional
addressing (list index) would reintroduce the exact fragility `pinned_turns` already has to work
around whenever a turn's position shifts.

| Node | Carries | Replaces |
|---|---|---|
| `TurnNode` | `id`, `role`, `content: RichContent`, `timestamp`, `model`, plus the branch lists below | the pre-ADR-019 `ChatMessage` — `tool_calls`/`footnotes`/`alternates` moved from flat fields to typed branches |
| `ToolCallNode` | `id`, `tool`, `args`, `result`, `status` | the pre-ADR-019 `ToolCallRecord` — now with a persisted `result`, which the old flat summary discarded |
| `ThinkingNode` | `id`, `thought`, `thought_number`, `revises`, `branches_from` | new — see "Thinking blocks" below. Schema only, see [Status](#status) |
| `CitedClaimNode` | `id`, `index`, `claim_text`, `sources`, `relation` (`citation`\|`attribution`\|`relational`), `faithfulness_checked` | the three sourced relations of the pre-ADR-019 [Footnote](claim.md) — see below |
| `InferenceNode` | `id`, `index`, `claim_text` | the pre-ADR-019 `ai-inference` relation — see below |

**`Footnote`/`FootnoteRelation` was replaced, not kept as flat attached data.**
`citation`/`attribution`/`relational` share real structure — each always has `sources`,
`claim_text`, and a meaningful `faithfulness_checked` — while what used to be the `ai-inference`
relation structurally never has `sources` and has nothing for `faithfulness_checked` to check at
all. One class trying to represent both was exactly the "union of two different shapes" problem
this codebase's other typed-modeling work (`RichContent`, the `Chat`/`ChatMessage` split) already
argues against. Splitting into `CitedClaimNode`/`InferenceNode` also folded the
inferred-vs-citation visual distinction (previously its own open item) into this work for free —
the UI distinction is a consequence of rendering two different node types, not a separate styling
decision layered on top of one uniform shape. See [Claim](claim.md) for the full field reference.

## Edge types

| Edge | From → To | Meaning | Replaces |
|---|---|---|---|
| `NEXT` | `TurnNode → TurnNode` | Main line: the user↔AI sequence | plain list order (unchanged — still implicit, no edge objects persisted) |
| `INVOKES` | `TurnNode → ToolCallNode` | This turn triggered this tool call (a `RECALL` call is also an `INVOKES` edge) | the pre-ADR-019 `tool_calls` summary |
| `REASONS` | `TurnNode → ThinkingNode` | This turn's reasoning steps | — new, see [Status](#status) |
| `REVISES` | `ThinkingNode → ThinkingNode` | A later thought revises an earlier one | — new, see [Status](#status) |
| `BRANCHES_FROM` | `ThinkingNode → ThinkingNode` | A thought forks an alternative reasoning path | — new, see [Status](#status) |
| `REGENERATES` | `TurnNode → TurnNode` | This attempt superseded that one | the pre-ADR-019 `alternates` (containment, not a change in shape) |
| `ASSERTS` | `TurnNode → CitedClaimNode \| InferenceNode` | This turn makes this claim | — |
| `CITES` | `CitedClaimNode → Note \| Source \| Chat` | This claim's sourcing (into the knowledge graph's vault nodes, see above) — **not** from `TurnNode` directly, since an `InferenceNode` structurally has nothing to cite | the pre-ADR-019 `Footnote.sources` |
| `PINNED_IN` | `TurnNode → Note` (the Excerpt) | This turn is source material for the Excerpt | `pinned_turns`/`excerpt_slug` (unchanged in shape) |
| `RECALLS` | `TurnNode → any node` | This turn's `RECALL` pulled in this node beyond the default rolling history — persisted as `TurnNode.recalls: list[RecallRef]` (`{node_id, node_kind}`), a pointer only, never a duplicate of the recalled content | new, see [`RECALL`'s resolved behavior](#recalls-resolved-behavior) below |

The key design call: `ToolCallNode`, `ThinkingNode`, `CitedClaimNode`, and `InferenceNode` are
never on the main line — `NEXT` only ever connects `TurnNode`s. "Just the conversation" is a
trivial `NEXT` walk; everything an orchestrator might selectively pull in is reached only by
following a branch edge, on demand.

## Thinking blocks (sequentialthinking)

Motivated by [MCP's `sequentialthinking` reference server](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking):
studied for its field shape, not adopted as an MCP integration (Prisma has no MCP client — its
tool loop is pattern-based markers, per [ADR-014](../wiki/adr/ADR-014-chat-llm-backend-interface.md)'s
appendix). Its tool does no inference itself — a calling model drives it by invoking it
repeatedly, self-reporting one reasoning step per call; per its own docs, it "requires only
standard tool-calling capabilities... any LLM supporting basic function calls can use it."
`ThinkingNode`/`REVISES`/`BRANCHES_FROM` above are that shape, generalized onto this graph.

This matters most specifically for local, hardware-constrained deployments (today's
`qwen2.5-3b`/`qwen2.5:7b-32k`): a `THINK:`-style marker tool is a way to get reasoning-*shaped*
behavior out of a small model's existing compute budget, not a nice-to-have for a cloud-backed
deployment that could just use a native reasoning model directly. When to advertise the tool in
the system prompt: the natural gate is a model-category flag (`has_native_reasoning`, see
[ADR-019](../wiki/adr/ADR-019-persisted-format-governance-and-migrations.md) §3a, itself
deferred), not a separate mechanism.

## SessionOrchestrator

The graph only answers "what *could* be loaded." A distinct component, the
**`SessionOrchestrator`**, is responsible for deciding what actually loads *this turn*,
replacing `ChatAgent`'s current fixed, uniform policy
(`_full_system_prompt()`/`_bounded_history()`: system prompt + tool section + Excerpt always,
raw history by token budget, oldest first, regardless of relevance) with an actual per-turn
selection decision over the graph. Not necessarily the same component as `ChatAgent` itself,
which today conflates "decide what context to send" with "run the tool-calling loop."

**Resolved (2026-08-05): relevance is decided in two separate places, neither of which is a new
loop.** This is the part worth being precise about, since it's easy to misread as "RECALL runs
its own search loop":

1. **Deciding *whether* anything's missing is the model's job, not the orchestrator's — expressed
   through the existing tool loop, not a new one.** The orchestrator's own default assembly is
   deliberately *not* relevance-aware: a cheap, no-LLM-call, purely algorithmic pass (existing
   precedent — `ChatAgent.excerpt_mode()`, `_bounded_history()`'s token trim are both deterministic
   thresholds already). Main-line `NEXT` walk bounded by the token budget, Excerpt always included,
   plus the *current* turn's own hot branches — that's it, no scoring, no ranking. It can't do
   better than that algorithmically: a similarity threshold over the whole graph, computed
   speculatively every turn whether needed or not, is an approximation, not understanding, and
   would cost an embedding pass on every turn even when nothing old is relevant. So the judgment
   of "am I missing something from earlier" is left entirely to the model, expressed the same way
   `SEARCH_VAULT`/`GRAPH_CONTEXT` already are: `RECALL:` is just a fourth marker tool in
   `chat_tools.py`'s `TOOLS` registry, invoked inside `ChatAgent`'s *existing*
   `MAX_TOOL_ITERATIONS` tool-calling loop. No RECALL-specific loop gets opened — it's one more
   option in the loop that's already there.
2. **Deciding *what's relevant*, once the model actually calls `RECALL`, is a single ranked pass —
   not iterative either.** One query embedding (`ChromaIndexer.embed_query()`), one cosine scan
   over the session graph's node texts, one greedy pack against the remaining token budget
   (`_pack_within_budget()`) — see "`RECALL`'s resolved behavior" below for the mechanics. There's
   no refinement loop inside a single `RECALL` call; if the first pass doesn't surface what the
   model needed, the model just calls `RECALL` again (bounded by `MAX_TOOL_ITERATIONS`, same as
   any other tool call repeating), it isn't the *ranking* itself iterating.

This is what makes it genuinely circular rather than a pipeline stage: the orchestrator feeds the
model context, the model's output (a tool call, a claim, a `RECALL` query) feeds new nodes back
into the graph, which the *next* turn's default assembly can itself walk over — but "circular"
describes the turn-over-turn relationship between orchestrator and model, not a search loop
inside `RECALL` itself.

### `RECALL`'s resolved behavior

- **Scope: the whole session graph, not just branches.** `_bounded_history()` already drops
  entire `TurnNode`s once the token budget is exceeded, oldest-first — a long conversation loses
  main-line turns today, not just tool results. `RECALL` searches everything (rolled-off
  `TurnNode`s included), which is the actual fix for "old turn referenced, already dropped" —
  not a narrower tool-result-only feature.
- **Engine: NetworkX for structure, an in-memory cosine scan for search — deliberately not Kùzu,
  and deliberately not a second Chroma collection either.** A session's own graph is small (dozens
  to a few hundred nodes even for a long chat); a full graph database or vector-index engine is
  the wrong tool at that scale. Considered and rejected: an in-memory-per-session Kùzu instance
  (`kuzu.Database(":memory:")` is real, verified against the installed `kuzu==0.11.3` API) —
  rejected because it's still a full DB engine for something this small, and its default
  `buffer_pool_size` (~80% of system RAM) is sized for one shared vault-wide instance, not N
  per-session ones. Also considered and rejected: a second, session-scoped ChromaDB collection —
  `ChromaIndexer` has exactly one hardcoded `"vault"` collection with no filter/multi-collection
  precedent, and chromadb's own indexing machinery is unneeded overhead for a few hundred vectors.
  What's actually built: `networkx.MultiDiGraph` (directed, multi-edge — a `TurnNode` can have
  several distinct edge types) built fresh from the `.sess` file's nodes/edges per active session,
  in-memory only, discarded when idle — no persistence, no staleness-vs-`.sess` drift to manage,
  essentially free to rebuild at this scale (`SessionOrchestrator.graph_for()`). `networkx` was
  already an installed *transitive* dependency (via `docu-craft`/`sysatlas`, not `kuzu`) — now
  declared directly in `pyproject.toml`. For the semantic-match half, `RECALL` reuses
  `ChromaIndexer.embed_texts()`/`embed_query()` (the same Ollama/OpenAI-compatible embedding call
  the vault index already uses — chromadb does no embedding of its own) to compute vectors, then
  does a plain numpy cosine scan over the session graph's own nodes — no chromadb collection or
  index involved at all. **Kùzu stays exactly what it already is — the vault-wide knowledge
  graph, untouched. ChromaDB stays exactly what it already is too — only its embedding-computation
  method is reused, its vault collection is never touched by `RECALL`.**
- **Trust carries forward, doesn't reset.** A recalled node was already wrapped as untrusted when
  first retrieved (`injection_defense.py`) — recalling it later must preserve that wrapping, not
  silently upgrade it to "trusted" just because it's now framed as "from the session" rather than
  "from the world."
- **Storage vs. context are different shapes.** The persisted `.sess` file stores `RECALL`'s
  result as a *reference* edge (`recalls: <node_id>`), not a duplicate of the text — otherwise
  every recall compounds the exact file-growth problem this redesign exists to fix. The
  dereferenced, fully-inlined text only exists in that turn's in-memory completion-call assembly,
  same as today's tool results are never persisted verbatim either.
- **Bounded the same way as everything else — no separate recall-depth limit, because there's
  nothing to bound inside a single call.** Each `RECALL` invocation does exactly one embed-rank-pack
  pass (see [SessionOrchestrator](#sessionorchestrator) above); a model that needs more just calls
  `RECALL` again, which is bounded the same way any repeated tool call already is, by the existing
  `MAX_TOOL_ITERATIONS` loop.
- **Not-found degrades, doesn't error** — same posture as `_regenerate_excerpt_now`'s
  `"(nothing pinned yet)"` and `_verify_claim`'s (renamed from `_verify_footnote`) silent skip.
- **Resource-aware via the existing lease mechanism, not a new one.** `resource_lock.lease()`
  already arbitrates shared local-compute contention (why `ChatLLM` takes a `priority` param, why
  `_chat_blocked_reason()` checks KG/Chroma activity) — but it retries internally for up to
  `max_wait=10.0s` by default before yielding `False`, not a fail-fast check. `RECALL`'s embedding
  call requests the same lease with an explicit short override —
  `resource_lock.lease(..., priority="interactive", max_wait=0.5)`, matching `ChatLLM`'s own
  `priority="interactive"` pattern for live chat — and degrades immediately to a cheap
  recency-order fallback on denial, rather than waiting or adding load to an already-stressed
  local machine.
- **Advertised unconditionally (all models)** — unlike `THINK:`, which stays gated by the
  deferred model-category flag (§3a). `RECALL` is core memory/retrieval, not a reasoning-shape
  emulation for weak models.
- **Size-aware.** Queries with an actual remaining-budget parameter
  (`context_window - already-assembled tokens`, the same accounting `respond()`'s existing
  overflow check already does), ranks candidates by relevance, greedily packs until the budget is
  exhausted — proactively self-limiting, not relying on the post-hoc overflow check to fail the
  whole turn the way an unbounded recall could.

## Relations

- Generalizes structure formerly flat inside [Chat](chat.md) (`ChatMessage.tool_calls`/
  `alternates`) and replaces the pre-ADR-019 [Footnote](claim.md)/`FootnoteRelation`
  (`CitedClaimNode`/`InferenceNode`, see "Node types" above).
- `CITES` edges (from `CitedClaimNode`, not `TurnNode`) point into
  [Note](note.md)/[Source](source.md)/`Chat` — the same resolution target as the pre-ADR-019
  `Footnote.sources`.
- `PINNED_IN` edges point at a chat's Excerpt [Note](note.md), same as `pinned_turns`/
  `excerpt_slug` (unchanged in shape by this redesign).
- Distinct from the vault-wide [GraphNode](graph-node.md) knowledge graph — see "What it is"
  above. `RECALL`'s NetworkX-backed traversal is deliberately a separate structure from Kùzu's
  vault-wide graph, not an extension of it.

## Status

Shipped 2026-08-05 (ADR-019 v2, `CHAT_SCHEMA_VERSION = 2`, with a v1→v2 migration for chats saved
before this cutover): the full node/edge taxonomy above, `SessionOrchestrator` (default assembly
+ `graph_for()`), and `RECALL` (`chat_tools.py`'s `TOOLS` registry) — all backed by tests,
including a real (not mocked) short `max_wait` exercise of `resource_lock.lease()`'s degrade path.
The frontend (`+page.svelte`) renders `claims`/`thoughts`/`recalls` per turn, styled per node
kind.

**Cross-session `RECALL` — also shipped 2026-08-05, same day it was raised.** `RECALL` now also
searches a bounded set of *other* chats' session graphs, not just the active one — cservinl's
framing: other chats searched "with a lower grade of attention" than the current one.

- **Scope cap**: only the `_RECALL_CROSS_CHAT_LIMIT` (8) most-recently-modified *other* chats
  (`VaultService.list_chats()`, sorted by `modified_at`) get their graph rebuilt and embedded per
  `RECALL` call — cservinl's justification: recalling every chat in the vault gets more expensive
  without bound as the vault grows, and the most recently active other chats are the ones most
  likely to actually be relevant to what's being discussed right now, so that's the
  well-justified place to cut rather than an arbitrary one. This is what keeps the engine-choice
  argument ("a session's own graph is small enough to rebuild for free, every call") true even
  with cross-chat search on — the cap bounds it back down to single-chat scale × a constant,
  not vault-wide scale.
- **The discount**: cross-chat candidates' cosine scores are multiplied by
  `_RECALL_CROSS_CHAT_DISCOUNT` (0.7) before ranking — an in-chat match wins unless a cross-chat
  one is substantially more relevant.
- **Addressing**: `RecallRef` gained `chat_slug: str | None` (`None` = same chat, otherwise the
  source chat's slug) — `node_id` alone is only unique within one chat's own graph.
- **Degrade path drops cross-chat entirely, doesn't guess**: when the embedding lease is denied
  or fails, `RECALL` degrades to recency order for the *active* chat only — there's no principled
  way to interleave cross-chat recency against a discount weight without embeddings, so it isn't
  attempted.
- **Active chat excluded** from its own cross-chat search (`_recent_other_chats()`) — its own
  candidates already arrive via `session_graph`, tagged `chat_slug: None`; nothing about this
  path re-adds them a second time, self-tagged.
- **Not free just because it's capped**: `list_chats()` fully parses every `.sess` file in the
  vault just to read `modified_at` off each, before the cap even applies — see the comment on
  `_recent_other_chats()`. Fine at today's vault-chat-count scale; a real per-turn latency
  regression here would call for a lightweight slug+`modified_at`-only listing, not a smaller cap.

Still genuinely open, not just undocumented:

- **`ThinkingNode` population.** The schema, `REASONS`/`REVISES`/`BRANCHES_FROM` edges, and
  `graph_for()`'s handling of them all exist — nothing produces a `ThinkingNode` yet. Gated behind
  the still-deferred model-category `has_native_reasoning` flag (ADR-019 §3a), out of scope until
  that flag lands.
- **`RECALL` relevance-ranking quality** — cosine similarity over `embed_texts()` vectors is the
  current ranking; nothing about the taxonomy or storage model would need to change if the ranking
  approach itself is later revisited, since ranking is purely an in-memory concern at query time.
- **Cross-chat scope beyond "N most recent"** — an explicit per-chat opt-in/link (rather than
  purely recency-driven) was considered and deliberately not built this pass — bigger scope than
  extending `RECALL`, would need its own UI/config, and recency already gives a reasonable default
  without asking the user to curate anything up front.
