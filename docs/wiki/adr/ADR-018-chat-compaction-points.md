# ADR-018: Chat Compaction Points

**Date:** 2026-08-04
**Author:** CServinL
**Status:** Superseded by [ADR-019](ADR-019-persisted-format-governance-and-migrations.md)
(2026-08-05). ADR-019 turned a chat's timeline from flat prose-with-metadata
into a graph (`TurnNode` main line + `tool_calls`/`thoughts`/`claims` branches,
`RECALL` for pulling in anything the rolling window dropped) — a single
`compaction_point: int | None` marker in a flat timeline is the wrong question
once turns are graph nodes with their own reachable structure, not just token
count to trim. The problem this ADR was chasing (long chats outgrowing the
model's context window) is still real; ADR-019's graph model plus `RECALL` is
now that answer instead of this design. Left below for the design history and
open-questions record, not as something to build.

## Context

[ADR-015](ADR-015-chat-excerpt-context-model.md) already solves part of this
problem: a user manually pins individual turns worth keeping, and all pinned
turns are folded into a single, durable Excerpt (compressed to a Summary, or
kept verbatim once a large-enough backend is configured). The Excerpt is
always included in full, on every turn, regardless of the rolling raw-history
budget (`ChatAgent.max_history_tokens`) — that's deliberate (curated content
shouldn't silently roll away), but it means the Excerpt itself has no upper
bound. A long-running chat with enough pinned turns can still exceed the
backend's real context window even though nothing about the mechanism caps
it. [ADR-015's 2026-08-04 addendum](ADR-015-chat-excerpt-context-model.md#context-window-overflow-guard-added-2026-08-04)
closed the *failure mode* (fail fast with an actionable error instead of a
confusing generic one) but not the *cause* — the only remedies today are
manual: unpin turns, or switch to a bigger-context model.

cservinl raised **compaction points** as a more proactive mechanism (2026-08-04):
an explicit marker in a chat's timeline after which the model resumes
considering context *from that point forward*, rather than the whole prior
history. Also raised: now that [ADR-017's 2026-08-04 persistence
fix](ADR-017-claim-attribution-and-footnote-model.md#persistence--ui-interactivity-fixes-added-2026-08-04)
makes every turn's `model`/`footnotes` a real, structured, reloadable part of
the chat file — not just its `content` string — a chat is effectively a full
structured document ("treating the session as a full DOM," cservinl's words),
not just flat prose. That richer structure is what would let a compaction
step reason about *what's actually redundant* (e.g. a claim already
established and footnoted earlier) rather than only "how many raw tokens are
old."

This is conceptually the same idea long-running agentic tools (this one
included) use for their own context windows: compact what's behind you into
a durable summary, keep working from the summary plus what's recent, instead
of carrying the entire transcript forever.

## How this relates to ADR-015 — the central open question

Compaction points and the Excerpt/pinned-turns system solve overlapping
problems (bounding what a long chat sends to the model) with different
mechanics:

| | Excerpt (ADR-015) | Compaction point (this ADR) |
|---|---|---|
| Granularity | Per-turn, opt-in (`pinned_turns`) | A single point in the timeline — everything before it, in one action |
| What's kept | Only turns the user explicitly pinned | Everything before the point, distilled |
| Growth | Unbounded (more pins = bigger Excerpt) | Bounded by construction — compacting again supersedes, doesn't add |
| User action | Pin/unpin any turn, any time | Mark "compact up to here" |

**Open question 1 (needs cservinl's decision): does a compaction point
replace pinning, or coexist with it?**

- *Replace*: simpler mental model, one mechanism instead of two, but loses
  the "curate exactly these specific turns, forever" guarantee pinning gives
  today — a compaction summary is a lossy distillation of *everything*
  before the point, not a verbatim preservation of *chosen* turns.
- *Coexist*: a compaction point still folds in whatever's currently pinned
  (so curated content isn't lost), and additionally summarizes/discards the
  *unpinned* turns before it. More faithful to both existing behavior and
  the new ask, but two mechanisms to reason about and explain in the UI.

This ADR assumes **coexist** below (it's the only option that doesn't
regress ADR-015's existing guarantee), but that's a default, not a decision
— flag if the intent was actually to replace pinning outright.

## Proposed model

```python
class Chat(VaultNodeBase):
    ...
    # Index into `messages`: turns at or after this index are sent to the
    # model in full (subject to the existing rolling max_history_tokens
    # trim); turns before it are represented only by compaction_summary_slug
    # (if set) or dropped from the model's context entirely. None = no
    # compaction has happened yet, behavior is unchanged from today.
    compaction_point: int | None = None
    # A Note, analogous to excerpt_slug -- the durable distillation of
    # everything before compaction_point. Regenerated (not appended to)
    # each time a *new*, later compaction point is set, same "machine-owned,
    # overwritten on regeneration" contract Excerpt already has.
    compaction_summary_slug: str | None = None
```

`ChatAgent._full_system_prompt()` would gain a compaction block, assembled
the same way `_excerpt_context_block()` is today — included whenever
`compaction_summary_slug` is set, positioned before the Excerpt block (older
context first, curated-pinned context second, closest to the live turns).

`_bounded_history()`'s rolling window would only ever consider
`history[compaction_point:]` — turns before the point are never candidates
for inclusion at all, compacted or not, since the summary already stands in
for them.

## Open questions (need cservinl's decision before implementation)

1. **Replace vs. coexist with pinning** — see above.
2. **Trigger: manual or automatic?** A manual "Compact up to here" action
   (explicit, like pin/unpin — predictable, no surprise LLM calls) vs.
   automatic (e.g. triggered once the rolling history budget would evict
   turns anyway — less user effort, but a new synchronous LLM-call
   dependency on a path that's currently pure bookkeeping, same tradeoff
   ADR-015's compressed mode already accepted for pin/unpin).
3. **Can there be more than one compaction point over a chat's life?** A
   later compaction point superseding an earlier one seems necessary for a
   genuinely long-running chat (otherwise you compact once and are back to
   unbounded growth after that point) — if so, does re-compacting fold the
   *previous* compaction summary into the new one (summary-of-a-summary,
   risk of drift/loss compounding), or always re-derive from the full raw
   history before the new point (more expensive, more faithful)?
4. **"Avoid duplicates" — what exactly?** cservinl's stated motivation for
   the structured-persistence connection. Two different things this could
   mean, needing different mechanisms:
   - *Avoid the compaction summary re-stating a claim already covered by a
     pinned Excerpt turn* — a prompt-construction concern (tell the
     summarization call what's already in the Excerpt, ask it not to
     repeat).
   - *Avoid the model re-asserting/re-searching something already
     established earlier in the same session* — a `respond()`-time concern
     (closer to how footnotes/`claim_text` already give per-claim structure
     to check against), and a much larger feature than compaction alone.
5. **Compression method for the compaction summary** — reuse
   `ChatAgent.complete_once()` + a new prompt (same mechanism as Excerpt's
   compressed-mode Summary regeneration), or something that explicitly
   consumes the newly-structured per-turn `footnotes`/`model` data (e.g. a
   summary that preserves which claims were already footnoted/verified,
   not just prose)? The latter is what actually cashes in the "full DOM, not
   flat text" framing, but is meaningfully more work than reusing the
   existing Excerpt summarization call as-is.

## Related

- [ADR-015](ADR-015-chat-excerpt-context-model.md) — Chat Excerpt & Context
  Model; this ADR is additive to it, not a replacement, pending open
  question 1 above.
- [ADR-017](ADR-017-claim-attribution-and-footnote-model.md) — the
  2026-08-04 persistence fix is what makes "treat the session as a full DOM"
  concretely true (structured `footnotes`/`model` per turn, not just prose),
  which motivated raising this ADR in the first place.
- [ADR-014](ADR-014-chat-llm-backend-interface.md) — whatever backend/model
  is configured is what a compaction summarization call would also run
  through.
