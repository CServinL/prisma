# Chat

## What it is

A **Chat** is a saved LLM session grounded in vault nodes. You bring Sources and Notes as
context; the model reasons over them, optionally pulling in more of the vault at answer time
via tool calls. No external (internet) retrieval happens at chat time — everything the model
sees traces back to something already in your vault.

Chats are saved as `.md` files in `vault/chats/`. Pinned turns from a chat are distilled into
a single [Note](note.md) (the chat's **Excerpt**, see below) rather than promoted piecemeal.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier |
| `title` | str | Display name |
| `messages` | list[`ChatMessage`] | Full turn history |
| `context_slugs` | list[str] | Vault node slugs used as context for this session |
| `model` | str | The model this chat is *currently* configured to use — overwritten on every turn, not a historical record (see `ChatMessage.model` below for that) |
| `pinned_turns` | list[int] | Indices into `messages` currently pinned into the Excerpt |
| `excerpt_slug` | str \| null | Slug of this chat's single Excerpt note, once one exists |
| `context_tokens_used` / `context_tokens_max` | int | API-response-only (never persisted) — how full the session's configured history budget is, see "Context management" below |

### ChatMessage fields

| Field | Type | Description |
|---|---|---|
| `role` | `ChatRole` | `user` \| `assistant` |
| `content` | str | Message text, with inline footnote markers in `[^N]` form |
| `timestamp` | datetime | |
| `tool_calls` | list[`ToolCallRecord`] | Which tools (`search_vault`, `graph_context`) this turn invoked, and with what query |
| `footnotes` | list[[Footnote](footnote.md)] | Per-claim attribution — what kind of sourcing backs each claim, and which document(s) |
| `model` | str \| null | The model that actually generated *this* message. `null` for user messages. Distinct from `Chat.model` (the chat's current setting): this is what generated this specific historical reply, so it stays correct even after the chat's active model changes |
| `html` | str \| null | API-response-only (never persisted) — sanitized HTML rendering of `content` for assistant messages (tables, code blocks, links, footnote markers as clickable spans). `null` for user messages |

## Tool use

The assistant can call two tools mid-turn by writing a recognized marker line (pattern-based,
not native function-calling — see [ADR-014](../wiki/adr/ADR-014-chat-llm-backend-interface.md)'s
appendix for why):

- **`SEARCH_VAULT`** — semantic search over the vault's ChromaDB embedding index. The default
  first step for almost any question about your notes/papers.
- **`GRAPH_CONTEXT`** — traverses the Knowledge Graph (entities and relationships extracted
  across the whole vault) to answer questions about how things connect, or when a vault search
  alone would likely come back scattered/incomplete.

Tool results are wrapped as untrusted content before entering the model's context (same
mechanism ingested documents use, see `prisma/services/injection_defense.py`) and shown in the
UI as a `used <tool>: <query>` line above the reply.

## Claim attribution & footnotes

Every substantive claim in an assistant reply is marked with where it came from — this is
Axiom 16 (see [Footnote](footnote.md) and [ADR-017](../wiki/adr/ADR-017-claim-attribution-and-footnote-model.md)):

- `citation` / `attribution` — traces to exactly one vault document (verbatim vs. paraphrased).
- `relational` — synthesizes across two or more documents (what a `GRAPH_CONTEXT` result usually produces).
- `ai-inference` — the model's own reasoning, no vault source.

Each footnote can also carry `faithfulness_checked` (`true` / `false` / `null` for "not
checked") — an automatic LLM-judge call, run on every turn for every sourced footnote, that
checks whether the claim actually represents what the cited source says. `null` means nothing
disqualified the check outright (e.g. an unresolvable source slug or a failed judge call), not
that the check passed.

In the UI, the inline `[^N]` marker is clickable (jumps to its footnote entry) and colored by
`relation`; the footnote list at the bottom shows the relation badge, the faithfulness badge
(when checked), and a clickable link to each cited source.

## Context management

Two independent budgets apply to what the model actually sees on a given turn:

- **Session history budget** (`ChatAgent.max_history_tokens`, shown as the UI's context label,
  e.g. `1.2k / 16k`) — a soft cap on how much *raw prior history* gets included; older turns
  roll off first. This is deliberately not the same number as the backend's real context
  window (see [ADR-015](../wiki/adr/ADR-015-chat-excerpt-context-model.md)'s "Resolved"
  section) — it answers "how full is this session's configured budget," not "how much of the
  model's total window is in use."
- **Excerpt** — pinned turns (`pinned_turns`) are distilled into a single durable note
  (`excerpt_slug`), always included in full regardless of the rolling history budget above.
  Compressed (LLM-summarized) or verbatim depending on the backend's real context window
  (ADR-015's mode switch) — today's local models stay compressed.

Because the Excerpt is never subject to the rolling trim, a chat with enough pinned turns (or
simply enough raw history + tool-result traffic) can still exceed the backend's *actual*
context window even while the session budget label looks fine. When that would happen, the
chat fails fast with an explicit message instead of a confusing generic "couldn't reach the
model" error:

> This chat's history and Excerpt exceed `<model>`'s context window (~N tokens estimated vs.
> an M-token limit) — I can't continue. Remove some pinned turns to free up context from
> Excerpt buildup, or switch this chat to a model with a bigger context window.

This check runs before every completion call in a turn (not just the first), so a tool result
that pushes an otherwise-fitting turn over the edge is caught too.

## System prompt

Chat's system prompt is user-editable, not baked into code or `config.toml` — it lives at
`~/.config/prisma/chat_system_prompt.md` (materialized with a sensible default on first use)
and is editable from the Settings page. It's a place for standing preferences ("always answer
in Spanish"), not one-off requests, which belong in the chat itself. The tool-calling and
footnote-marker instructions are separate, always-appended sections generated from code (not
part of this file), since they're tied to the exact marker syntax the parser expects.

## Persistence

`model` and `footnotes` are stored per message as a `<!-- prisma:meta {...} -->` JSON comment
alongside the existing `### You` / `### Prisma` markdown transcript — invisible in a plain
markdown viewer, parsed back out on load. A malformed or hand-edited comment degrades to "no
metadata for this turn" rather than breaking the rest of the chat.

## Relations

- Uses [Source](source.md)s and [Note](note.md)s as context (via `context_slugs`), and can pull
  in more at answer time via `SEARCH_VAULT`/`GRAPH_CONTEXT`.
- Its Excerpt is a [Note](note.md), linked via `excerpt_slug`.
- Indexed as a [GraphNode](graph-node.md).
- Each assistant `ChatMessage` carries [Footnote](footnote.md)s referencing the `Note`/`Source`
  slugs its claims are attributed to.

## Relevant axioms

> Chats are grounded. A chat uses only vault nodes as context. See [Axiom 5](../ontologia.md).
>
> Claims are footnoted — distinct from grounding, this is about whether each individual claim
> in the output is marked as sourced or as the model's own inference. See
> [Axiom 16](../ontologia.md) and [Footnote](footnote.md).

## Not yet implemented

- **Compaction points** — an explicit marker in the chat timeline after which the model would
  only consider context from that point forward (plus the Excerpt), rather than pin/unpin
  being the only way to control what's durable. Needs to be designed against the existing
  Excerpt/pinned-turns system, not as a parallel mechanism.
- **Rich rendering, frontend half** — the backend now renders every assistant message to
  sanitized HTML (`ChatMessage.html`, via `services/chat_render.py` + a new `nh3`-based
  allowlist sanitizer wired into `services/renderer.py`, so Notes/Sources get it too) —
  tables, code blocks, and links all work. Not yet wired into the UI: `+page.svelte` still
  renders via the old plain-text `renderContentSegments()` path instead of `{@html}` + a
  click-delegate action for the `.footnote-marker` spans the backend now emits. Needs live
  browser verification before landing.
