# Chat session graph

## What it is

A **proposed** redesign of how a [Chat](chat.md) represents its own internal structure — not
another vault node type, a different shape for what's already inside `Chat.messages`. Today a
`Chat` is a flat `messages: list[ChatMessage]`, each carrying a flat `tool_calls` *summary*
(name + args, no result) and, since turn regeneration, an `alternates` list. Two things are
missing: intermediate tool-call results and reasoning steps are never persisted at all (they
exist only transiently inside `ChatAgent.respond()`'s tool loop, for the one completion call
that produced them), and there is no general way to ask "what produced this turn" beyond the one
special-cased `alternates` field.

The session graph reframes a chat as a **main line of `User <-> AI` turns, with everything else
— tool calls, reasoning steps, past regeneration attempts — as branches off that line**, not
competing with it for position in a flat list. This is what makes selective context loading
possible: an [orchestrator](#masterai--orchestrator) can walk the main line for free and only
follow a branch edge when a turn actually needs it, instead of "everything within a token
budget, oldest-first" (today's `ChatAgent._bounded_history()`) or "everything pre-compressed
into one Summary" (the [Excerpt](chat.md), [ADR-015](../wiki/adr/ADR-015-chat-excerpt-context-model.md)).

Not a rename of the [knowledge graph](graph-node.md) — that graph connects vault-wide *content*
(entities/relationships extracted from Notes/Sources across the whole vault, queried via
`GRAPH_CONTEXT`). This graph is scoped to *one chat session's own internal flow*. A chat's
`CITES` edges (below) point *into* the knowledge graph's vault nodes, but the two graphs are
otherwise independent structures serving different questions.

## Node types

| Node | Carries | Generalizes |
|---|---|---|
| `TurnNode` | `role`, `content: RichContent`, `timestamp`, `model` | today's `ChatMessage`, minus `tool_calls`/`footnotes`/`alternates` — those become edges/attachments below |
| `ToolCallNode` | `tool`, `args`, `result`, `status` | today's `ToolCallRecord` — now with a persisted `result`, which today's flat summary discards |
| `ThinkingNode` | `thought`, `thought_number` | new — see "Thinking blocks" below |
| `CitedClaimNode` | `claim_text`, `sources`, `relation` (`citation`\|`attribution`\|`relational`), `faithfulness_checked` | the three sourced [Footnote](footnote.md) relations — see below |
| `InferenceNode` | `claim_text` | the `ai-inference` relation — see below |

**`Footnote`/`FootnoteRelation` is replaced, not kept as flat attached data** (a correction from
this page's earlier version). `citation`/`attribution`/`relational` share real structure — each
always has `sources`, `claim_text`, and a meaningful `faithfulness_checked` — while `ai-inference`
structurally never has `sources` and has nothing for `faithfulness_checked` to check at all. One
class trying to represent both was exactly the "union of two different shapes" problem this
session's other typed-modeling work (`RichContent`, the `Chat`/`ChatMessage` split) already
argues against. Splitting into `CitedClaimNode`/`InferenceNode` also folds the
inferred-vs-citation visual distinction (previously its own open item) into this work for free —
the UI distinction becomes a consequence of rendering two different node types, not a separate
styling decision layered on top of one uniform shape.

## Edge types

| Edge | From → To | Meaning | Generalizes |
|---|---|---|---|
| `NEXT` | `TurnNode → TurnNode` | Main line: the user↔AI sequence | today's list order |
| `INVOKES` | `TurnNode → ToolCallNode` | This turn triggered this tool call (a `RECALL` call — see below — is also an `INVOKES` edge) | today's `tool_calls` |
| `REASONS` | `TurnNode → ThinkingNode` | This turn's reasoning steps | — |
| `REVISES` | `ThinkingNode → ThinkingNode` | A later thought revises an earlier one | — |
| `BRANCHES_FROM` | `ThinkingNode → ThinkingNode` | A thought forks an alternative reasoning path | — |
| `REGENERATES` | `TurnNode → TurnNode` | This attempt superseded that one | today's `alternates` |
| `ASSERTS` | `TurnNode → CitedClaimNode \| InferenceNode` | This turn makes this claim | — |
| `CITES` | `CitedClaimNode → Note \| Source \| Chat` | This claim's sourcing (into the knowledge graph's vault nodes, see above) — **not** from `TurnNode` directly, since an `InferenceNode` structurally has nothing to cite | today's `Footnote.sources` |
| `PINNED_IN` | `TurnNode → Note` (the Excerpt) | This turn is source material for the Excerpt | today's `pinned_turns`/`excerpt_slug` |

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

## MasterAI / orchestrator

The graph only answers "what *could* be loaded." A distinct component — cservinl's naming:
**MasterAI / orchestrator / harness** — is responsible for deciding what actually loads *this
turn*, replacing `ChatAgent`'s current fixed, uniform policy
(`_full_system_prompt()`/`_bounded_history()`: system prompt + tool section + Excerpt always,
raw history by token budget, oldest first, regardless of relevance) with an actual per-turn
selection decision over the graph. Not necessarily the same component as `ChatAgent` itself,
which today conflates "decide what context to send" with "run the tool-calling loop."

**Resolved (2026-08-05): not a one-shot filter — a loop, the same shape `ChatAgent`'s tool
calling already is.** A plain algorithmic pre-filter can't be semantically correct (a similarity
threshold is an approximation, not understanding), and the LLM itself is often in the best
position to know it's missing something — so the orchestrator doesn't gate what the model ever
sees, it participates in the same circular exchange `SEARCH_VAULT`/`GRAPH_CONTEXT` already are:
it feeds the model context, the model's output (a tool call, a claim, a recall request) feeds
new nodes back into the graph, which the *next* turn's assembly can itself select over.
Concretely, two parts:

1. **Cheap algorithmic default assembly** — no LLM call, existing precedent
   (`ChatAgent.excerpt_mode()`, `_bounded_history()`'s token trim are both deterministic
   thresholds today). Main-line `NEXT` walk bounded by the existing token budget, Excerpt always
   included (both as today), plus the *current* turn's own hot branches (its own tool
   calls/reasoning, already "in scope" the same way they are today). This covers the common turn
   at today's cost — most turns don't need anything older at all.
2. **`RECALL:` — a fourth marker tool, same registry as `SEARCH_VAULT`/`GRAPH_CONTEXT`**
   (`chat_tools.py`'s `TOOLS`), not a separate mechanism. Free-text query, same marker syntax
   (`RECALL: that search result about Kùzu's embedded mode`) — no node IDs, the model thinks in
   terms of what was discussed, not database keys.

This is what makes it genuinely circular rather than a pipeline stage: the orchestrator and the
LLM both read from and write to the same graph, in the same turn.

### `RECALL`'s resolved behavior

- **Scope: the whole session graph, not just branches.** `_bounded_history()` already drops
  entire `TurnNode`s once the token budget is exceeded, oldest-first — a long conversation loses
  main-line turns today, not just tool results. `RECALL` searches everything (rolled-off
  `TurnNode`s included), which is the actual fix for "old turn referenced, already dropped" —
  not a narrower tool-result-only feature.
- **Engine: NetworkX for structure, Chroma for search — deliberately not Kùzu.** A session's own
  graph is small (dozens to a few hundred nodes even for a long chat); a full graph database
  engine is the wrong tool at that scale. Considered and rejected: an in-memory-per-session Kùzu
  instance (`kuzu.Database(":memory:")` is real, verified against the installed `kuzu==0.11.3`
  API) — rejected because it's still a full DB engine for something this small, and its default
  `buffer_pool_size` (~80% of system RAM) is sized for one shared vault-wide instance, not N
  per-session ones. Instead: `networkx.MultiDiGraph` (directed, multi-edge — a `TurnNode` can
  have several distinct edge types) built fresh from the `.sess` file's nodes/edges per active
  session, in-memory only, discarded when idle — no persistence, no staleness-vs-`.sess` drift to
  manage, essentially free to rebuild at this scale. `networkx` was already an installed
  *transitive* dependency (via `docu-craft`/`sysatlas`, not `kuzu`) — now declared directly in
  `pyproject.toml` rather than relied on implicitly. Chroma (existing `ChromaIndexer`,
  session-scoped collection/filter, separate from the vault's own) handles the semantic-match
  half — "which nodes match this query" is Chroma's job, "what's connected to a match, and how"
  (e.g. pulling in the `TurnNode` that `INVOKES` a matched `ToolCallNode`) is NetworkX's.
  **Kùzu stays exactly what it already is — the vault-wide knowledge graph, untouched.**
- **Trust carries forward, doesn't reset.** A recalled node was already wrapped as untrusted when
  first retrieved (`injection_defense.py`) — recalling it later must preserve that wrapping, not
  silently upgrade it to "trusted" just because it's now framed as "from the session" rather than
  "from the world."
- **Storage vs. context are different shapes.** The persisted `.sess` file stores `RECALL`'s
  result as a *reference* edge (`recalls: <node_id>`), not a duplicate of the text — otherwise
  every recall compounds the exact file-growth problem this redesign exists to fix. The
  dereferenced, fully-inlined text only exists in that turn's in-memory completion-call assembly,
  same as today's tool results are never persisted verbatim either.
- **Bounded the same way as everything else** — inside the existing `MAX_TOOL_ITERATIONS` loop,
  no separate recall-depth limit.
- **Not-found degrades, doesn't error** — same posture as `_regenerate_excerpt_now`'s
  `"(nothing pinned yet)"` and `_verify_footnote`'s silent skip.
- **Resource-aware via the existing lease mechanism, not a new one.** `resource_lock.lease()`
  already arbitrates shared local-compute contention (why `ChatLLM` takes a `priority` param, why
  `_chat_blocked_reason()` checks KG/Chroma activity). `RECALL`'s own Chroma/NetworkX work should
  request the same lease; on denial, degrade to a cheap deterministic fallback
  (recency/keyword match) rather than waiting or adding load to an already-stressed local
  machine. **Not yet verified** against `resource_lock.py`'s actual API — flagged, not confirmed.
- **Advertised unconditionally (all models)** — unlike `THINK:`, which stays gated by the
  deferred model-category flag (§3a). `RECALL` is core memory/retrieval, not a reasoning-shape
  emulation for weak models.
- **Size-aware.** Queries with an actual remaining-budget parameter
  (`context_window - already-assembled tokens`, the same accounting `respond()`'s existing
  overflow check already does), ranks candidates by relevance, greedily packs until the budget is
  exhausted — proactively self-limiting, not relying on the post-hoc overflow check to fail the
  whole turn the way an unbounded recall could.

## Relations

- Generalizes structure currently inside [Chat](chat.md) (`ChatMessage.tool_calls`/`alternates`)
  and replaces [Footnote](footnote.md)/`FootnoteRelation` (`CitedClaimNode`/`InferenceNode`,
  see "Node types" above).
- `CITES` edges (from `CitedClaimNode`, not `TurnNode`) point into
  [Note](note.md)/[Source](source.md)/`Chat` — the same resolution target as
  `Footnote.sources` today.
- `PINNED_IN` edges point at a chat's Excerpt [Note](note.md), same as `pinned_turns`/
  `excerpt_slug` today.
- Distinct from the vault-wide [GraphNode](graph-node.md) knowledge graph — see "What it is"
  above. `RECALL`'s NetworkX-backed traversal is deliberately a separate structure from Kùzu's
  vault-wide graph, not an extension of it.

## Not yet implemented

Everything on this page is design-only (raised 2026-08-05, in the same session `.sess` shipped —
see [ADR-019](../wiki/adr/ADR-019-persisted-format-governance-and-migrations.md)'s "Open
direction" section). This is a second, breaking redesign of the `.sess` format already shipped.
Still open: whether `ToolCallNode.result` becomes persisted content in full (raw tool text can be
large — a policy question, not just a schema one), `resource_lock.lease()`'s exact integration
(API not yet verified against the real module), `RECALL`'s relevance-ranking specifics, and how
this interacts with Excerpt/`context_slugs` loading. A full audit of what today's code becomes
obsolete or needs rework once this lands exists (discussed 2026-08-05) but is deliberately not
written down yet — revisit before implementation starts, not before. Needs its own plan-mode pass
before implementation, not ad hoc coding on top of the current shape.
