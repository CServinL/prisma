# ADR-015: Chat Excerpt & Context Model

**Date:** 2026-07-03
**Author:** CServinL
**Status:** Accepted — fully built (2026-07-03). See `TODO.md`'s "Chat
memory model" section for the concrete implementation of all three pieces:
compressed mode, verbatim mode + the budget-driven mode switch
(`ChatAgent.excerpt_mode()`), and the context-usage label
(`ChatAgent.context_usage()` + the UI's `k`/`M`-formatted display). Verbatim
mode has no practical effect yet since only the local, small-context
`prisma-llm:7b` is configured — it activates automatically whenever a
larger-context backend is, no further code changes needed.

## Context

The chat module's first increment (`TODO.md`, "Chat memory model — 'meeting,
not the meeting notes'") built promotion as: each pinned turn becomes its
own independent `Note`, appended to `Chat.promoted_excerpts`, and every note
in that list is re-injected into the system prompt on every turn — always,
uncounted against `ChatAgent._bounded_history()`'s rolling token budget.

Working with it live surfaced a mismatch with the intended mental model.
The chat itself is a sandbox — a rolling, disposable working session,
correctly subject to `_bounded_history`'s eviction. But "promoted" content
was implemented as N *separate* vault notes per chat, when the actual intent
is closer to: **one Excerpt per chat** — a single durable artifact distilled
from whichever turns get pinned, not a growing pile of independent notes.
The UI's "Promote to Note" label and per-note "Pin" buttons already read
wrong under this framing (a screenshot-driven catch: "the pin button is
'promoting to note' and that's not correct, the whole excerpt is considered
a note").

Two more gaps, once the single-Excerpt framing is accepted:

1. **No visibility into context cost.** Promoted notes are always injected,
   uncounted — there's no way to see how much of the model's actual context
   window they (or the rolling history) are consuming.
2. **No compression.** Every pinned turn's raw text is retained forever,
   growing the system prompt injection linearly with pin count. Nothing in
   the current design gives back the context budget that pinning is meant to
   free up from the rolling window.

## Proposed model

One **Excerpt** per chat (replacing the current N-separate-`Note`s design):

- **Summary** (top): an LLM-generated distillation of the currently pinned
  turns. Regenerated whenever the pinned set changes (pin or unpin).
- **Raw copy** (below the summary, same document): the pinned turns
  themselves, verbatim, in pin order — an audit trail / fallback in case the
  summary drops or distorts something specific that was pinned to preserve
  it exactly.
- A **context label** in the UI (e.g. `122 / 2000`) showing live token usage
  of the chat's actual assembled context, so the cost of history + Summary +
  raw copy is visible, not implicit.

`Chat.pinned_excerpts` (see the excerpt-pinning work earlier this session)
already gives per-item pin/unpin without deletion — this model reuses that,
but changes what pinning *produces* (one regenerated Excerpt, not N
independent notes) and what unpinning means for context cost (see the two
modes below).

## Decision: both modes, selected by the backend's real context budget

Rather than pick one of "pinned turns stay verbatim in context" vs "pinned
turns compress into the Summary and stop being resent," both get built,
switched by how much context budget the configured chat backend actually
has to spend — cservinl's own framing: "currently we need the compressed
context... because of the small context window we got... but if we start
using a cloud 1M-context model then we could have the real pinned items."
The tradeoff genuinely depends on the backend, not on some universally
correct answer:

### Compressed mode (today's local `prisma-llm:7b`, 32768 real ctx)

Once a turn is pinned and folded into the Summary, its raw text stops being
resent to the model as part of ongoing context — only the Summary
represents it going forward. The raw copy still exists (in the Excerpt
document, and in the chat's own persisted history) for human reference,
just not resent. This is the mode where "the Summary is a condensed version
of what we're removing from context" is literally true — budget actually
gets freed. Necessary while context is the scarce, expensive resource it is
locally.

### Verbatim mode (a future large-context cloud backend, e.g. ~1M ctx)

Pinned turns stay in the model's context exactly as written, exempt from
`_bounded_history`'s eviction — no compression, no summary-fidelity risk.
Once context is abundant relative to how much a real chat session
accumulates, there's no real reason to compress at all; the Summary (if
shown) becomes more of a quick-reference index on top of the still-present
raw pins than a replacement for them.

### Selecting between them

A config value on the chat backend (`ChatConfig.context_window`, alongside
`provider`/`model`/`pool`) declaring its real context ceiling — reusing the
same "verified via `/api/ps`'s `context_length`, not the Modelfile's
claimed value" discipline established in ADR-013's follow-up section.

`ChatAgent.excerpt_mode()` requires **two** conditions for verbatim, not
one — a single "pinned content is a small fraction of the window" check
turned out to be wrong in practice: a typical single pinned turn is a small
fraction of *any* window, including today's local 32768-token one, so that
check alone put the local model into verbatim mode almost immediately
(observed live: pinning one turn never showed a Summary at all). The fix:

1. `context_window` must itself clear `LARGE_CONTEXT_WINDOW_THRESHOLD`
   (200,000) before verbatim is even considered — today's local model
   (32768) always stays compressed, unconditionally, regardless of how
   small the pinned set is.
2. Only once that's cleared does the percentage check apply: pinned
   content must be at most `VERBATIM_MODE_MAX_RATIO` (15%) of the window,
   so even a large-context backend can still fall back to compressed mode
   if the pinned set is genuinely enormous.

Both thresholds are budget-driven constants, not a hardcoded per-provider
flag, so this keeps working correctly if a "large-context" backend turns
out not to be large enough in practice, or a future local model ships with
a much bigger real ceiling than today's.

## Resolved: what the context label's two numbers mean

cservinl's example (`122 / 2000`) used illustrative numbers, not the real
default. Confirmed meaning: **first number is the current session's actual
assembled context size** (system prompt + rolling history + Summary + raw
copy, all counted); **second number is the max allowed for that session**
— i.e. `ChatAgent`'s `max_history_tokens` budget (`DEFAULT_MAX_HISTORY_TOKENS`,
currently 16000), not the model's raw hardware context ceiling (32768). The
label answers "how full is this session's configured budget," not "how
much of the model's total window is in use."

Display format: human-readable with `k`/`M` suffixes (e.g. `1.2k / 16k`,
or `850 / 16k` below 1000), not raw token counts. This is a new formatting
convention for the UI — the Compute Pools page's numbers
(`vram_budget_mb.toLocaleString()`) use comma-grouping instead (`14,000
MB`), not k/M suffixes, so this isn't reusing an existing helper; a small
`formatTokenCount()`-style function will need to be added when the label is
built.

## Consequences (once built)

### Positive
- Matches cservinl's actual mental model — one Excerpt per chat, not a
  pile of independent notes with a confusingly-labeled "Promote to Note"
  action.
- In compressed mode, pinning becomes real, visible context compression,
  not just "exempt from eviction" bookkeeping — the context label should
  visibly drop after a pin causes a summary regeneration that displaces raw
  turns. In verbatim mode, pinning is simply reliable (no fidelity risk),
  appropriate once context is cheap.
- Raw pinned content is never actually lost in either mode — still
  recoverable from the Excerpt document's raw-copy section and the chat's
  own persisted history.
- The mode switch is automatic (budget-driven), so moving chat to a
  large-context cloud backend later (ADR-014's Option B/D) upgrades pinning
  behavior for free, no new code path to opt into.

### Negative
- Compressed mode costs a real LLM call on every pin/unpin (summary
  regeneration) — a new synchronous dependency on Ollama availability/GPU
  contention for what was previously a pure vault-write operation. Verbatim
  mode avoids this entirely.
- Summary quality risk in compressed mode: a bad regeneration could
  misrepresent or drop something the user specifically pinned to preserve —
  this is exactly what the raw-copy section exists to hedge against, but
  it's a real quality surface verbatim mode doesn't have.
- Requires rethinking the `promoted_excerpts`/`pinned_excerpts` data model
  and the `/chats/{slug}/promote` + `/chats/{slug}/excerpts/{note_slug}/pin`
  endpoints built earlier this session — not a pure additive change, some
  of that surface gets replaced, not extended.
- Two code paths to maintain (compressed vs verbatim assembly) instead of
  one — real complexity cost for supporting both, though the alternative
  (picking one mode forever) would mean either wasting a large-context
  backend's headroom or risking overflow on a small-context one.

## Related

- `TODO.md`, "Chat memory model — 'meeting, not the meeting notes'"
  (2026-07-02) — the design this ADR supersedes/refines.
- ADR-014: Chat Module's LLM Backend Interface — whatever backend/model is
  configured for chat is also what compressed mode's Summary regeneration
  call would use, and what verbatim mode's context-ceiling check reads.
