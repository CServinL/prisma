# Chat

## What it is

A **Chat** is a saved LLM session grounded in vault nodes. You bring Sources and Notes as
context; the model reasons over them, optionally pulling in more of the vault at answer time
via tool calls. No external (internet) retrieval happens at chat time — everything the model
sees traces back to something already in your vault.

Chats are saved as pure-JSON `.sess` files in `vault/chats/` (ADR-019) — the only vault node
type that isn't `.md`, since only the Excerpt (see below) is genuinely prose; everything else a
chat persists is structured, typed data. Pinned turns from a chat are distilled into a single
[Note](note.md) (the chat's **Excerpt**, see below) rather than promoted piecemeal.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier |
| `title` | str | Display name |
| `messages` | list[`TurnNode`] | The main line of the [session graph](chat-session-graph.md) — full turn history, list order = `NEXT` |
| `context_slugs` | list[str] | Vault node slugs used as context for this session |
| `model` | str | The model this chat is *currently* configured to use — overwritten on every turn, not a historical record (see `TurnNode.model` below for that) |
| `pinned_turns` | list[int] | Indices into `messages` currently pinned into the Excerpt |
| `excerpt_slug` | str \| null | Slug of this chat's single Excerpt note, once one exists |
| `context_tokens_used` / `context_tokens_max` | int | API-response-only (never persisted) — how full the session's configured history budget is, see "Context management" below |

### TurnNode fields

The main-line node type of the [session graph](chat-session-graph.md) — everything else a turn
produces (tool calls, claims, past regeneration attempts, session-graph recalls) branches off it
rather than sharing its position in `messages`. See that page for the full node/edge taxonomy;
this table is just the fields directly on `TurnNode` itself.

| Field | Type | Description |
|---|---|---|
| `id` | str | Stable node id (uuid4) — how branches and `RecallRef`s address a specific turn regardless of its position in `messages` |
| `role` | `ChatRole` | `user` \| `assistant` |
| `content` | `RichContent` | `{format, value, rendered_html}` — the text layer (ADR-019's two-layer model). `format` supports `md`/`html`/`svg`/`latex`; only `md` is actually rendered today. `rendered_html` is API-response-only (sanitized HTML of `value`, computed fresh on every read, never persisted) — the UI deliberately does not use it for chat turns (see "Rendering" below), it exists for future format support and any other consumer |
| `timestamp` | datetime | |
| `tool_calls` | list[`ToolCallNode`] | Which tools (`search_vault`, `graph_context`, `recall`) this turn invoked, with what args, and — unlike the pre-ADR-019 model — the persisted `result` too, so a later turn's `RECALL` can find it |
| `thoughts` | list[`ThinkingNode`] | Reasoning steps. Schema support only today — nothing populates this yet, see [Chat session graph](chat-session-graph.md#status) |
| `claims` | list[[Claim](claim.md)] (`CitedClaimNode` \| `InferenceNode`) | Per-claim attribution — what kind of sourcing backs each claim, and which document(s) |
| `model` | str \| null | The model that actually generated *this* message. `null` for user messages. Distinct from `Chat.model` (the chat's current setting): this is what generated this specific historical reply, so it stays correct even after the chat's active model changes |
| `alternates` | list[`TurnNode`] | Prior attempts at this same turn, preserved (not discarded) when regenerated via `POST /chats/{slug}/turns/{index}/regenerate` — each alternate keeps its own `model`, so different models' answers to the same prompt stay comparable |
| `recalls` | list[`RecallRef`] | Pointers to session-graph nodes this turn's `RECALL` calls pulled in beyond the default rolling history — a reference, never a duplicate of the recalled content, see [Chat session graph](chat-session-graph.md) |
| `media` | list[`MediaNode`] | v3 — media the *assistant* generated this turn (`PRODUCES` edge). Schema only, no generator exists for any kind yet — see [Chat session graph](chat-session-graph.md#media-nodes) |
| `attachments` | list[`MediaNode`] | v3 — media the *human* attached as input this turn (`ATTACHES` edge). See "Attachments" below |
| `attached_slugs` | list[str] | v3 — vault `Note`/`Source`/`Chat` slugs the human referenced as input this turn (conceptually `REFERENCES`, not a graph edge — see [Chat session graph](chat-session-graph.md#attachments-human-turn-input)) |

## Tool use

The assistant can call tools mid-turn by writing a recognized marker line (pattern-based, not
native function-calling — see [ADR-014](../wiki/adr/ADR-014-chat-llm-backend-interface.md)'s
appendix for why):

- **`SEARCH_VAULT`** — semantic search over the vault's ChromaDB embedding index. The default
  first step for almost any question about your notes/papers.
- **`GRAPH_CONTEXT`** — traverses the Knowledge Graph (entities and relationships extracted
  across the whole vault) to answer questions about how things connect, or when a vault search
  alone would likely come back scattered/incomplete.
- **`RECALL`** — searches this chat's own [session graph](chat-session-graph.md), including
  turns the rolling history window has already dropped. Not a vault search — this is the
  session's own memory, not the vault's.

Tool results are wrapped as untrusted content before entering the model's context (same
mechanism ingested documents use, see `prisma/services/injection_defense.py`) and shown in the
UI as a `used <tool>: <query>` line above the reply.

## Claims

Every substantive claim in an assistant reply is marked with where it came from — this is
Axiom 16 (see [Claim](claim.md), [ADR-017](../wiki/adr/ADR-017-claim-attribution-and-footnote-model.md),
[ADR-019](../wiki/adr/ADR-019-persisted-format-governance-and-migrations.md)):

- `CitedClaimNode`, `relation == citation` / `attribution` — traces to exactly one vault document
  (verbatim vs. paraphrased).
- `CitedClaimNode`, `relation == relational` — synthesizes across two or more documents (what a
  `GRAPH_CONTEXT` result usually produces).
- `InferenceNode` — the model's own reasoning, no vault source, structurally distinct from
  `CitedClaimNode` rather than a same-shape variant of it (see [Claim](claim.md#build-status)).

Every `CitedClaimNode` can also carry `faithfulness_checked` (`true` / `false` / `null` for "not
checked") — an automatic LLM-judge call, run on every turn for every sourced claim, that checks
whether it actually represents what the cited source says. `null` means nothing disqualified the
check outright (e.g. an unresolvable source slug or a failed judge call), not that the check
passed.

In the UI, the inline `[^N]` marker is clickable (jumps to its claim's list entry) and colored by
relation/kind; the claim list at the bottom shows the relation/kind badge, the faithfulness badge
(when checked, `CitedClaimNode` only), a clickable link to each cited source, and — below that,
ADR-020 — the source's formatted APA citation, fetched on demand via `GET /notes/apa?slugs=...`
(`services/citation_format.py`'s `format_apa()`, resolved fresh on every request, not cached) and
cached client-side per slug so re-rendering the same chat doesn't re-fetch.

Since v3, a claim can also carry a Toulmin `qualifier`/`warrant`/`rebuts` — schema and rendering
exist, nothing populates them yet. See [Claim](claim.md) and
[Chat session graph](chat-session-graph.md#argumentation-structure-toulmin).

## Attachments

Since v3, a human turn can bring in more than plain text: an image or PDF (uploaded), an inline
SVG/LaTeX/draw.io snippet (pasted), or a reference to an existing vault node (`attached_slugs`) —
via the compose box's attachment toolbar. Two distinct paths, not one:

- **Ephemeral (default)** — `POST /chats/{slug}/attachments/upload` (jpg/pdf) or a client-built
  inline snippet lands in that turn's own `attachments`, scoped to this chat's session graph only
  (memory tier L1 when sent, L2 once the turn rolls off the active history window — see
  [Chat session graph](chat-session-graph.md#memory-tiers-l1--l2--l3)). Never indexed, never
  searchable outside this one chat.
- **Promoted (deliberate)** — `POST /chats/{slug}/attachments/promote` turns any attachment (or a
  freshly-uploaded one) into a real vault [Note](note.md) with a companion file, referenced from
  then on via `attached_slugs` instead — indexed, searchable, outlives this chat entirely (memory
  tier L3). A promoted `.pdf` gets real extracted body text (`docu_craft`'s PDF→MD conversion,
  the same conversion `POST /zotero/import` uses, generalized in v3 to not require Zotero), not
  just an empty body.

Honesty about what's not built yet: `svg`/`latex`/`drawio` attachments render as an unstyled code
block, not as an actual diagram/formula — no rendering pipeline exists for any of the three. A
`jpg` attachment can't actually be *seen* by the model at all — `ChatLLM.complete()` is text-only,
no multimodal/vision path exists in the transport layer. See
[Chat session graph](chat-session-graph.md#attachments-human-turn-input) for the full mechanics.

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
claim-marker instructions are separate, always-appended sections generated from code (not
part of this file), since they're tied to the exact marker syntax the parser expects.

## Model selection

`Chat.model` is the chat's *currently configured* model — but it's not sticky in the way that
phrase implies: every turn's `POST /chat` call overwrites it with whatever the server's single
globally-configured `ChatAgent` is currently running (`_vault.append_messages(..., model=
_chat_agent.model)`). There's no per-chat default-model override today; changing which model a
chat *keeps* using means changing the server-side config, not a per-chat UI setting.

What does exist, since v3: `GET /models` lists what's actually available (Ollama's `/api/tags`
for `ollama`/`llama_cpp`, degrading to just the current model for other providers or if discovery
fails) — populating a per-turn model picker next to **Regenerate**. Picking a model there is a
genuine one-off override (`RegenerateTurnRequest.model` → `_build_chat_agent_for_model()`,
predates v3 — only the discovery UI was missing), preserved as that turn's `alternates` entry, and
never touches `Chat.model` itself (see `regenerate_turn`'s own docstring: "a real model switch is
a separate, deliberate action").

## Rendering

Model-generated text is treated as untrusted (same posture as tool results, see
`prisma/services/injection_defense.py`) — the UI deliberately renders a turn's `content.value`
as escaped plain text with just its `[^N]` claim markers turned into clickable elements
(`renderContentSegments()` in `+page.svelte`), never `{@html}`. `content.rendered_html` (sanitized
markdown → HTML, via `services/chat_render.py` + the `nh3`-based sanitizer in
`services/renderer.py`) is still computed and returned by the API on every read, for future
format support and any other consumer — it's just not what the chat UI displays today. This is a
deliberate, final choice, not a stopgap waiting to be wired up.

## Persistence

A `Chat` is stored as pure JSON at `vault/chats/<slug>.sess` (ADR-019) — every field on this
page's tables above, `schema_version`-governed (`schema_gov.VersionedModel`). Not markdown, not
frontmatter, no embedded-comment convention: only the Excerpt (below) is genuinely prose, so only
the Excerpt stays a `.md` file. `VaultService`'s chat methods (`get_chat`/`create_chat`/
`save_chat`/`append_messages`/`set_pinned_turns`/`save_excerpt`) all read/write this JSON
directly. A legacy `.md`-with-`<!-- prisma:meta {...} -->`-comment reader survives, read-only, in
`vault.py`, solely so `prisma migrate-chats-to-sess` can convert chats saved before this cutover.

## Relations

- Uses [Source](source.md)s and [Note](note.md)s as context (via `context_slugs`), and can pull
  in more at answer time via `SEARCH_VAULT`/`GRAPH_CONTEXT`/`RECALL`.
- Its Excerpt is a [Note](note.md), linked via `excerpt_slug`.
- **Not** indexed as a [GraphNode](graph-node.md) — the knowledge-graph indexer only walks `.md`
  files, so a `.sess` chat is invisible to it by construction (deliberate, ADR-019: KG coverage
  of chat-derived content goes through the Excerpt `Note` only, which *is* `.md` and *is*
  indexed).
- Each assistant `TurnNode` carries [Claim](claim.md)s referencing the `Note`/`Source` slugs its
  claims are attributed to.
- `messages` is the main line (`NEXT`) of the [Chat session graph](chat-session-graph.md) — see
  that page for how tool calls, reasoning, claims, regeneration attempts, and recalls branch off
  each `TurnNode`.

## Relevant axioms

> Chats are grounded. A chat uses only vault nodes as context. See [Axiom 5](../ontologia.md).
>
> Claims are footnoted — distinct from grounding, this is about whether each individual claim
> in the output is marked as sourced or as the model's own inference. See
> [Axiom 16](../ontologia.md) and [Claim](claim.md).

## Not yet implemented

- **Toulmin claim population** — `qualifier`/`warrant`/`rebuts` ship as schema (v3, 2026-08-17)
  and render if present, but `ChatAgent`'s self-reporting doesn't produce them yet.
- **Media rendering** — `svg`/`latex`/`drawio` (both `media` and `attachments`) render as an
  unstyled code block; no diagram/formula rendering pipeline exists. No generator exists either
  (nothing turns a request into a `media` entry today).
- **Vision/multimodal input** — a `jpg` attachment is stored and displayable in the UI, but the
  model itself can't see it; `ChatLLM.complete()` has no multimodal path.
- **Sticky per-chat model override** — see "Model selection" above; today only a one-off
  regenerate override exists, not a way to change which model a chat defaults to going forward.
