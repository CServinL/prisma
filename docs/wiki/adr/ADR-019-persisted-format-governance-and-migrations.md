# ADR-019: Persisted Format Governance & Migrations

**Date:** 2026-08-04 (chat sessions cut over to `.sess` 2026-08-05)
**Author:** CServinL
**Status:** Implemented in two cutovers. (1) 2026-08-05: chat sessions fully
cut over to the `.sess` pure-JSON format (`Chat`/`RichContent` in
`prisma/storage/models/vault_models.py`, governed by the generic
`prisma.schema_gov` package), Python-only by design (see open question 2:
chat sessions never touch Rust). The legacy `prisma:meta`-in-markdown shape
is now read-only, kept solely for `prisma migrate-chats-to-sess` to convert
pre-existing `.md` chat files. (2) 2026-08-05, same day: the "Open
direction" session-as-a-graph redesign below also shipped —
`Chat.messages: list[TurnNode]` (renamed from `ChatMessage`) plus
`ToolCallNode`/`ThinkingNode`/`CitedClaimNode`/`InferenceNode` branches,
`SessionOrchestrator`, and the `RECALL` tool, `CHAT_SCHEMA_VERSION = 2` with
a v1→v2 migration. See [Chat session graph](../../concepts/chat-session-graph.md)
for the full node/edge taxonomy and current status, not restated here. Open
questions 1/3 (extending versioning to vault frontmatter generally, and
where migration logic should live for that broader case) still need
cservinl's decision — the only parts of this ADR still actually open.

## Context

[ADR-017's 2026-08-04 persistence fix](ADR-017-claim-attribution-and-footnote-model.md#persistence--ui-interactivity-fixes-added-2026-08-04)
added a `<!-- prisma:meta {...} -->` JSON blob to the chat `.md` format,
carrying `model`/`footnotes` per turn. Writing it surfaced a gap: **nothing
in this codebase tracks what shape a persisted file's data is in.** Every
format change so far has been handled ad hoc, three different ways:

- **Per-field Pydantic defaults** (`Field(default_factory=...)`,
  `#[serde(default = "fn")]` on the prisma-desktop/Rust side) — works for
  *adding* an optional field, silently wrong for a *rename* or a field whose
  *meaning* changes (a default can't know "this old value meant something
  different").
- **Defensive parsing** (`_parse_chat_body`'s meta-comment handling, this
  same session: malformed JSON degrades to "no metadata," never breaks
  loading the rest of the chat) — good for surviving corruption, says
  nothing about *which* shape a file is actually in, so it can't
  distinguish "old format, needs upgrading" from "genuinely malformed."
- **Dual-format acceptance** (`_parse_frontmatter` still accepts a legacy
  HTML-comment style alongside YAML, per its own docstring) — works, but
  each instance is a bespoke one-off with no shared pattern, and the
  original format's acceptance code has no expiry — it stays forever
  because nothing marks it as "old."

None of these answer "what schema version is this file on" or give a
single, testable place to put an upgrade step when the format changes
again. cservinl asked for real governance over this — a versioned format
plus explicit migrations, done through Pydantic where it fits rather than
ad hoc per call site.

## Decision (narrow instance, built 2026-08-04, now legacy-only)

The original narrow instance, kept read-only for `prisma migrate-chats-to-sess`
(see the resolution below): the `prisma:meta` JSON blob carried its own
`schema_version`, checked and upgraded through a single dispatch function
before its contents were used:

```python
CHAT_META_SCHEMA_VERSION = 1

def _migrate_chat_meta(raw: dict) -> dict:
    version = raw.get("schema_version", 1)  # absent = written before this
                                              # existed (2026-08-04 same-day
                                              # code), already shape v1
    if version > CHAT_META_SCHEMA_VERSION:
        raise ValueError(
            f"prisma:meta schema_version {version} is newer than this "
            f"build supports ({CHAT_META_SCHEMA_VERSION})"
        )
    # No migrations yet -- next format change adds a step here:
    #   if version == 1:
    #       raw = {...upgraded...}
    #       version = 2
    # Never rewrite an existing step once shipped -- each version's
    # upgrade path must stay independently correct for a file frozen at
    # that version, however old.
    return raw
```

Composes with the existing defensive-parsing contract for free: `_parse_chat_body`
already catches `ValueError` around the meta-comment JSON decode and
degrades to "no metadata for this turn" rather than breaking chat load —
`_migrate_chat_meta` raising for an unrecognized future version (an older
binary reading a file a newer one wrote) falls into that same path, no new
exception handling needed.

This mechanism no longer runs on any live write path — chats write `.sess`
JSON now (`Chat.SCHEMA_VERSION`/`schema_gov.VersionedModel`, see below),
which carries its own, separate `schema_version`. Kept here only because
`_parse_chat_body`/`_migrate_chat_meta` are still the read path for
converting old `.md` chat files.

## Chat sessions are not `.md` (resolved 2026-08-04, built 2026-08-05)

cservinl's framing: of everything a Chat persists, only the **Excerpt**
(the distilled Summary note, ADR-015) is genuinely prose — the rest
(`tool_calls`, `footnotes`, `model`) is structured, typed data that had
been getting *embedded inside* a `.md` file via increasingly elaborate
conventions layered on top of plain markdown (`> used \`tool\`: query`
blockquote lines, then this ADR's `<!-- prisma:meta {...} -->` JSON-in-
HTML-comment). Each of those was markdown *abused* to carry non-markdown
data, not markdown used for what it's actually good at. `.md` earns its
keep for Notes/Sources/the Excerpt — genuinely-prose content a plain
markdown viewer should render meaningfully — but a chat session's
structured metadata was never really prose to begin with.

**Resolution, now built**: chats moved to their own file type, `vault/chats/<slug>.sess`
(pure JSON, ADR-019 `schema_version` governance applied directly, no
markdown-embedding tricks). Two-layer model: a **session layer**
(`Chat`/`ChatMessage` in `vault_models.py` — flow: role, timestamps, tool
calls, footnotes, model, `alternates` for regenerated turns) and a **text
layer** (`schema_gov.RichContent` — `{format, value, rendered_html}`,
`format` supports `md`/`html`/`svg`/`latex` today, only `md` actually
rendered). `VaultService`'s chat methods (`get_chat`/`create_chat`/
`save_chat`/`append_messages`/`set_pinned_turns`/`save_excerpt`) all
read/write `.sess` JSON directly — the markdown parse path
(`_parse_chat_body`/`_migrate_chat_meta`) survives only as a read-only
helper for `prisma migrate-chats-to-sess`, the one-time converter for
pre-existing `.md` chat files (not yet run against the real vault — a
deliberate, separate action). The Excerpt note is unaffected: still a real
`.md` `Note`.

One real, deliberate side effect: `KnowledgeGraphService` only walks `.md`
files and derives trust tier from frontmatter, so it indexed raw chat
transcripts at trust tier `"chat"` before this change. Since `.sess` files
are outside that walk, KG coverage of chat-derived content now goes through
the Excerpt `Note` only (already `.md`, already indexed at trust tier
`"note"`) — no code change made to `knowledge_graph_service.py` for this,
the old `NodeType.chat: "chat"` trust-tier mapping simply stops being
reachable. If a future consumer needs the raw transcript beyond the
Excerpt, the right shape is a `.sess`-side render-to-markdown helper called
directly against an already-resolved `Chat`, not a filesystem walk over
`.sess` files.

## Open questions (scope — need cservinl's decision)

This narrow instance only versions the chat `prisma:meta` blob, the
newest/freshest format in the codebase and the one that motivated raising
this. Left open:

1. **Extend to vault frontmatter generally** (Notes/Sources/Chats/Streams'
   `---` YAML block)? The dual-format `_parse_frontmatter` HTML-comment/YAML
   acceptance is the same class of problem, just older and already
   papered over a different way — a `schema_version` key in frontmatter
   would let that legacy-acceptance branch eventually be *removed* on
   purpose (once no unversioned/old-format files remain) instead of staying
   forever. Bigger surface: every vault entity's Pydantic model, not just
   one JSON blob.
2. **Chat session structure is server-only — no cross-language transport
   needed for it.** prisma-desktop's sync engine never parses `.md`/`.sess`
   content (confirmed by direct inspection: `push.rs`/`pull.rs` treat every
   file as an opaque byte blob); its role is a webview onto the same web UI
   Python serves, plus byte-level file sync. Even offline chat editing
   routes through a *local* prisma-server, never Rust reconstructing
   session data itself — so `ChatSession`/`SessionMessage`/`RichContent`
   have exactly one implementation, in Python, and stay that way.

   `settings.json` is a separate case: genuinely Rust-only data, no Python
   involvement ever. If it ever needs the same kind of versioned governance
   this ADR built for `prisma:meta`, JSON Schema is the standard,
   well-tooled way to define/validate it — Pydantic v2 exports JSON Schema
   natively (`model.model_json_schema()`, no new Python dependency), and
   Rust has two real, actively-maintained options: the
   [`jsonschema`](https://docs.rs/jsonschema) crate (validates JSON against
   a schema, additive — existing hand-written structs stay as-is) or
   [`typify`](https://docs.rs/typify) (Oxide Computer — generates Rust
   structs directly from a JSON Schema, a bigger change since it replaces
   hand-written structs with generated ones). `jsonschema` (validate-only)
   is the better fit if this is ever built: `settings.json`'s surface is
   small, and a validation guard rail is proportionate to that.

   The generic `schema_gov` Rust module (migration chain + `jsonschema`
   validation wrapper, zero references to any prisma-desktop domain type)
   exists as tested groundwork for exactly that `settings.json` case — not
   because chat sessions need it, since they don't touch Rust at all.
3. **Where does migration *logic* belong for the broader (frontmatter)
   case — inside each Pydantic model via `model_validator(mode="before")`,
   or in the vault-layer parse functions (`vault.py`), like this narrow
   instance?** A `model_validator` keeps migration co-located with the
   model it upgrades (governance the model itself owns, matching
   cservinl's "maybe even pydantic" framing) and applies automatically to
   *any* code path constructing that model from a raw dict, not just the
   one parse function that happens to call it explicitly. The tradeoff:
   several of this codebase's vault entities are assembled from multiple
   pieces (frontmatter dict + parsed body content, e.g. `_parse_chat_body`
   builds `ChatMessage` from a regex match *and* the meta comment, not a
   single raw dict) — a `model_validator(mode="before")` needs one raw
   dict to operate on, which may mean restructuring how a few of these
   parse functions assemble their inputs before construction, not just
   adding a validator.

## Open direction: session as a graph, not a flat list (raised 2026-08-05)

Prompted by looking at [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)
(a team-oriented multi-agent memory platform — evaluated and explicitly
**not adopted**: single-vendor, ~4 months old, only 2 contributors despite
14.8k stars, ambiguous `NOASSERTION` license, no interoperable protocol the
way MCP has one). Its Chat Memory layer is graph-shaped; the underlying
edge model is the useful part, not its Mermaid visualization or its
team/ACL machinery, neither of which fits Prisma's single-user, local-first
design.

`Chat`/`ChatMessage` (this ADR's cutover, above) is still a flat
`messages: list[ChatMessage]`, each with a flat `tool_calls` *summary*
(name + query args only). `ChatAgent.respond()`'s tool loop
(`prisma/agents/chat_agent.py`) round-trips intermediate LLM↔tool exchanges
— the tool call, its raw result text, any interim reasoning — only in a
local, in-memory list built for that one completion call; none of it is
persisted. `alternates` (turn regeneration, above) is the one place a real
edge already exists (`ChatMessage → alternates[]`), but it's informal, not
a general graph a session could otherwise traverse.

cservinl's framing: `UserTurn#23 -> AITurn#34 -> chroma_search() -> results
-> AITurn#45 -> ...`, with a main branch of `User <-> primary-AI-answer`
turns and tool calls/results as leaves off that branch, not separate
top-level messages. Thinking/reasoning steps (a model's intermediate
chain-of-thought before it commits to a final answer, as many agentic
setups now surface) belong in the same category as tool-call branches, not
on the main line: a loop off the current turn, not revisited or reloaded
into later turns by default — only pulled back in when something
specifically needs it (debugging, an explicit "show your reasoning," a
faithfulness re-check), same selective-load principle as the rest of this
section, applied to a second kind of branch besides tool calls. This also
reframes context management:
`ChatAgent._bounded_history()` currently drops the *oldest* turns wholesale
once a token budget is hit, and ADR-015's Excerpt / ADR-018's not-yet-built
compaction points both work by point-in-time *summarization* (collapse a
span into one Summary, always reload the whole thing). If turns/tool
results were addressable graph nodes instead of list positions, a turn
could selectively pull in just the nodes it actually needs rather than
"everything within budget, oldest-first" or "everything pre-compressed" —
context growth per turn is mostly repeated tool-call noise today, and
neither current mechanism is actually selective about what it keeps.

**A concrete anchor for the thinking-branch case**: the MCP reference server
[`sequentialthinking`](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking)
is worth studying not to adopt as an MCP integration (Prisma has no MCP
client today — its tool loop is pattern-based markers, per ADR-014's
appendix), but for its field shape, which is exactly this branch's edges
already made concrete: `thought`/`thoughtNumber`/`totalThoughts`/
`nextThoughtNeeded` (the main sequence), `isRevision`/`revisesThought` (a
revision edge back to an earlier thought), `branchFromThought`/`branchId`
(a fork). Verified directly against its README: the tool itself does no
inference — it's a state-tracking scaffold the calling model drives by
invoking it repeatedly; it "requires only standard tool-calling
capabilities... any LLM supporting basic function calls can use it." That
means a `THINK:`-style marker tool with the same fields could be added to
`chat_tools.py`'s existing `TOOLS` registry the same way `SEARCH_VAULT`/
`GRAPH_CONTEXT` already work, no new integration surface needed. When to
advertise it: exactly for models *without* native reasoning (most local
3B-7B chat models, unlike o1/QwQ/DeepSeek-R1/Qwen3-thinking variants) —
the natural gate is §3a's deferred model-category work (a
`has_native_reasoning`-style category flag), not a separate mechanism.
This matters most precisely where Prisma already lives: local, hardware-
constrained deployments (today's `qwen2.5-3b`/`qwen2.5:7b-32k`) can't just
swap in a bigger native-reasoning model to get better multi-step answers —
a `THINK:`-style scaffold is a way to get reasoning-*shaped* behavior out
of a small model's existing compute budget, not a nice-to-have for a
cloud-backed deployment that could just use a reasoning model directly.

A graph of addressable nodes only solves half of this — something still has
to decide, per turn, *which* nodes to load: the **`SessionOrchestrator`**.
Resolved (2026-08-05, corrected
from an earlier algorithmic-only framing this same day): it isn't a
one-shot pre-filter gating what the model sees — a pure algorithmic
threshold can't be semantically correct, and the model itself is often in
the best position to know it's missing something, so the orchestrator
feeds and takes from both the LLM and the user turn, the same circular
shape `ChatAgent`'s existing `SEARCH_VAULT`/`GRAPH_CONTEXT` tool loop
already is — a cheap algorithmic default assembly (main line + Excerpt +
the current turn's own branches, no LLM call) plus a `RECALL:` marker tool
in that same loop for anything the model decides is missing. Full writeup,
kept current: [Chat session graph](../../concepts/chat-session-graph.md).

**Not scoped or designed here** — this page states the resolved direction,
the concept doc is where the taxonomy/algorithm actually live and get
revised. Shipped 2026-08-05, the same day this direction was raised: this
was a second, breaking redesign of the same `.sess` shape this ADR's first
cutover landed (`CHAT_SCHEMA_VERSION = 2`, v1→v2 migration) — node/edge
shape, `ToolCallNode.result` persisted in full, `RECALL`'s search
implementation (embedding reuse + in-memory cosine scan, not a new Chroma
collection or a Kùzu instance), `ChatAgent`/`SessionOrchestrator`
responsibility split, and Excerpt/`context_slugs` interaction (unchanged —
the orchestrator's default assembly still includes the Excerpt exactly as
before) are all resolved. Cross-chat `RECALL` (a bounded, discounted search of other chats'
session graphs, not just the active one) shipped the same day it was raised, 2026-08-05. See
[Chat session graph](../../concepts/chat-session-graph.md#status) for what's still genuinely open
(`ThinkingNode` population, and cross-chat scope beyond "N most recently active").

## Related

- [ADR-017](ADR-017-claim-attribution-and-footnote-model.md) — the
  `prisma:meta` persistence fix this governance was raised in response to.
- [ADR-015](ADR-015-chat-excerpt-context-model.md) and
  [ADR-018](ADR-018-chat-compaction-points.md) — the point-in-time
  summarization approach the graph direction above would partly reframe.
- `prisma-desktop/src-tauri/src/settings.rs` — the Rust-side instance of
  the same underlying problem (open question 2 above).
