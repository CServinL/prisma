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

`Footnote` is **not** a node — it stays attached data on a `TurnNode` (an annotation about
content already there), the same as it is today.

## Edge types

| Edge | From → To | Meaning | Generalizes |
|---|---|---|---|
| `NEXT` | `TurnNode → TurnNode` | Main line: the user↔AI sequence | today's list order |
| `INVOKES` | `TurnNode → ToolCallNode` | This turn triggered this tool call | today's `tool_calls` |
| `REASONS` | `TurnNode → ThinkingNode` | This turn's reasoning steps | — |
| `REVISES` | `ThinkingNode → ThinkingNode` | A later thought revises an earlier one | — |
| `BRANCHES_FROM` | `ThinkingNode → ThinkingNode` | A thought forks an alternative reasoning path | — |
| `REGENERATES` | `TurnNode → TurnNode` | This attempt superseded that one | today's `alternates` |
| `CITES` | `TurnNode → Note \| Source \| Chat` | A claim's sourcing (into the knowledge graph's vault nodes, see above) | today's `Footnote.sources` |
| `PINNED_IN` | `TurnNode → Note` (the Excerpt) | This turn is source material for the Excerpt | today's `pinned_turns`/`excerpt_slug` |

The key design call: `ToolCallNode` and `ThinkingNode` are never on the main line — `NEXT` only
ever connects `TurnNode`s. "Just the conversation" is a trivial `NEXT` walk; everything an
orchestrator might selectively pull in is reached only by following a branch edge, on demand.

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

**Open, not settled**: should selection be LLM-based or algorithmic? Leaning algorithmic-first —
an LLM call *to decide what context to send the LLM* is circular, and fights the local-hardware
motivation above directly. Existing precedent in this codebase already favors deterministic
thresholds for orchestration (`ChatAgent.excerpt_mode()`, `_bounded_history()`'s token trim),
reserving LLM calls for content work (the answer, summarization, faithfulness checks). Candidate
algorithmic signals: main-line `NEXT` walk bounded by the existing token budget, Excerpt always
included (both as today), branch inclusion gated by recency/proximity or ChromaDB embedding
similarity between the current user message and a branch's content (a vector op, already how
`search_vault` works elsewhere, not a model call).

## Relations

- Generalizes structure currently inside [Chat](chat.md) (`ChatMessage.tool_calls`/`alternates`).
- `CITES` edges point into [Note](note.md)/[Source](source.md)/`Chat` — the same resolution
  target as [Footnote](footnote.md)`.sources` today.
- `PINNED_IN` edges point at a chat's Excerpt [Note](note.md), same as `pinned_turns`/
  `excerpt_slug` today.
- Distinct from the vault-wide [GraphNode](graph-node.md) knowledge graph — see "What it is"
  above.

## Not yet implemented

Everything on this page is design-only (raised 2026-08-05, in the same session `.sess` shipped —
see [ADR-019](../wiki/adr/ADR-019-persisted-format-governance-and-migrations.md)'s "Open
direction" section). This is a second, breaking redesign of the `.sess` format already shipped —
node/edge shape, whether `ToolCallNode.result` becomes persisted content (raw tool text can be
large — a policy question, not just a schema one), the LLM-vs-algorithmic orchestrator fork
above, and how this interacts with Excerpt/`context_slugs` loading are all open. Needs its own
plan-mode pass before implementation, not ad hoc coding on top of the current shape.
