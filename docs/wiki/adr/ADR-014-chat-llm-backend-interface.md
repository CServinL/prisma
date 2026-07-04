# ADR-014: Chat Module's LLM Backend Interface

**Date:** 2026-07-02
**Author:** CServinL
**Status:** Accepted

## Context

The chat module (`TODO.md`, "Chat module (Phase 2)") needs an LLM call path
that isn't hardcoded to one backend the way `analysis_agent.py` and
`knowledge_graph_service.py` are today (both call Ollama's `/api/generate`
directly via `requests`). Prisma's stated design intent is cross-backend for
chat specifically — Ollama first, then OpenRouter, then Anthropic's own API
— because chat is the one place in this system where a user might
deliberately reach for a more capable cloud model rather than the local
7B-class model everything else uses. `compute_pools`' `model_affinity:
false` (ADR-012) already anticipated an auto-scaled/non-GPU-constrained
pool for exactly this case.

Three real options exist for how the chat module talks to whichever backend
is configured. This ADR is scoped narrowly to that one interface — it does
not cover the agentic tool-loop, the sanitizer, or the tool contracts
(`TODO.md` already has those, unaffected by this choice).

## Options Considered

### Option A: `litellm`

A wrapper library that normalizes ~100 providers (including Ollama,
OpenRouter, and Anthropic's real API) behind one call shape:
`litellm.completion(model="ollama/prisma-kg:7b", messages=[...])` or
`litellm.completion(model="anthropic/claude-...", messages=[...])`, always
returning the same OpenAI-shaped response regardless of what the backend
actually speaks.

**Pros:**
- Anthropic's native API has a genuinely different message/response shape
  than OpenAI's (different field names, tool-call structure, no `system`
  role inside the messages array). `litellm` ships that translation
  already; switching to Anthropic later is a model-string change, not new
  adapter code.
- Built-in per-provider retry/backoff for transient API errors (rate
  limits, 5xxs) — the module already needs *some* retry strategy for cloud
  calls, since `prisma.services.backoff` (used by `resource_lock.lease()`)
  solves a different problem (waiting for a local GPU pool slot to free up)
  and doesn't apply to "OpenRouter returned a 429."
- Optional automatic fallback routing (try model A, fall back to model B on
  failure) — not required now, but available without new code if wanted
  later (e.g., "try local Ollama, fall back to cloud if unreachable").
- One dependency instead of `openai` + a hand-written Anthropic adapter +
  whatever retry logic that adapter would need.

**Cons:**
- Meaningfully heavier dependency: pulls in `tiktoken` (OpenAI-specific
  tokenizer, not accurate for the actual models this project runs — Qwen2.5
  locally, whatever cloud model is configured — so it's along for the ride
  rather than doing useful work here) and a handful of other transitive
  deps, for ~100 provider integrations this project will only ever use 2-3
  of.
- More surface area than `requests`-based code elsewhere in this codebase
  (`analysis_agent.py`, `knowledge_graph_service.py`) — a new pattern to
  reason about, not a continuation of the existing one.
- Version-pin risk: fast-moving library (weekly-ish releases), adds one
  more thing that can introduce breaking changes on upgrade.

### Option B: `openai` SDK, multi-`base_url`

Ollama exposes an OpenAI-compatible `/v1/chat/completions` endpoint, and
OpenRouter is natively OpenAI-API-compatible. The official `openai` Python
SDK, pointed at each backend's `base_url` + `api_key`, covers both with
zero custom request/response parsing, including real streaming and
tool-calling support. Anthropic would need a small dedicated adapter (their
own `anthropic` SDK, or their beta OpenAI-compat endpoint) when that
backend is actually built — not needed for the Ollama-only scope today.

**Pros:**
- Minimal, well-scoped dependency — one official SDK, no unrelated
  provider integrations riding along.
- Matches this codebase's general preference for direct, minimal
  dependencies (ADR-003) more closely than a unifying framework does.
- `prisma` already depended on `openai>=1.0` at one point (removed when
  Graphify — the code that used it — was replaced; see ADR-013). Not a
  reason by itself, but shows it was already an accepted, working
  dependency in this project before.

**Cons:**
- Anthropic support is not free — needs a hand-written adapter mapping
  Anthropic's actual message/response shape onto whatever internal
  `ChatMessage`/`ChatResponse` model this module standardizes on. Moderate,
  one-time, well-understood work (Anthropic's API is well documented), but
  real work `litellm` would skip.
- No built-in retry/backoff for cloud-API-specific failures (rate limits,
  transient 5xxs) — would need to be written, e.g. reusing
  `prisma.services.backoff`'s existing exponential-backoff-with-jitter
  primitive, but wired to different trigger conditions (HTTP status codes)
  than its current use (waiting for a local GPU pool slot).
- No automatic cross-provider fallback routing — would be entirely
  hand-rolled if wanted later.

### Option D: LiteLLM's Rust gateway, as its own supervised worker (not yet available)

Announced 2026 (blog post, no GA date given), LiteLLM is rewriting its
*self-hosted proxy/gateway* — a separate mode from the Python SDK discussed
in Option A — in Rust: same unified OpenAI-compatible API and provider
coverage, terminating requests, routing, retries, and fallback itself, but
as a single compiled binary (~65MB memory under load, vs. ~358MB for the
existing Python proxy; per-request overhead claimed to drop from ~7.5ms to
~0.05ms). Config, client API, and behavior are stated to be unchanged from
the Python proxy — a performance/footprint rewrite, not a redesign.

Under this option, `api` never imports `litellm`'s Python package at all —
it talks to the gateway using the plain `openai` SDK pointed at
`localhost:<port>/v1`, and the gateway process does the Ollama/OpenRouter/
Anthropic translation, retry, and fallback on the other side. Architecturally
this is the same supervised-worker pattern already used for `chroma` and
`kg` (ADR-012/ADR-013) — a 5th worker process.

**Would resolve, if/when available:**
- Removes Option A's dependency-weight con entirely — `api`'s own
  dependency stays as light as Option B (`openai` SDK only, no `tiktoken`
  or the Python `litellm` package).
- Still gets Anthropic-shape translation and retry/fallback "for free,"
  same as Option A, just implemented on the other side of an HTTP call
  instead of in-process.
- Crash-isolated from `api` for free, same benefit ADR-012/013 already
  established for `chroma`/`kg`.

**New cons this option introduces:**
- **Not released yet — no GA date.** Not a real option today; noted here so
  it isn't rediscovered as if new later. Revisit once it ships and has a
  track record.
- One more supervised process/port, with its own `config.yaml` and provider
  key management to maintain — real operational weight even though the
  binary itself is small.
- A local network hop (loopback HTTP) added to every chat LLM call that
  Options A/B don't have, though at loopback scale this is unlikely to be
  the bottleneck for LLM calls specifically (unlike, say, per-embedding
  ChromaDB calls — ADR-012's future-consideration section already discusses
  this exact latency tradeoff for a different call site).

### Option C: Hand-rolled, plain `requests`

Same pattern as `analysis_agent.py`/`knowledge_graph_service.py` today: one
private HTTP call per backend, parsed manually. Zero new dependency.

**Rejected outright**, not seriously weighed against the others: it
means hand-writing and maintaining three different request/response
parsers (Ollama, OpenRouter, Anthropic) plus streaming plus tool-call
parsing plus retry logic for all three, none of which this project gains
anything from owning versus a well-maintained SDK. The existing
`requests`-based pattern elsewhere works because those call sites talk to
exactly one backend each, permanently — the chat module's whole premise is
*not* being locked to one backend.

## Discussion

The actual scope difference between Option A and Option B is narrower than
it first looks: for the Ollama-only case this module ships with today, both
are a few lines of code. The entire question is what happens when
OpenRouter/Anthropic get added later — Option A pays that cost up front (as
dependency weight, today) so it's free later; Option B defers that cost (as
one Anthropic adapter, written later) so today's dependency footprint stays
minimal.

Given cservinl's own framing — chat is specifically the component most
likely to want "a very intelligent cloud model," not a hypothetical future
nice-to-have — the multi-backend need is closer to a known near-term
requirement than a speculative one, which weakens the usual "don't build
for hypothetical future requirements" argument against Option A.

Option D would resolve Option A's main con (dependency weight) entirely,
by moving `litellm` out of the `api` process and into its own worker — but
it isn't available yet (no GA date on the Rust gateway as of this writing).
Not actionable today; recorded here as the option to switch to once it
ships and has a track record, since it would let this decision be revisited
without changing anything about the chat module's own code (only where the
OpenAI-shaped HTTP calls actually land) if Option A or B is chosen now.

## Decision

**Option B: `openai` SDK, multi-`base_url`.** Ollama and OpenRouter are
covered today/soon by pointing the SDK at each backend's OpenAI-compatible
endpoint; Anthropic gets a small dedicated adapter when that backend is
actually built.

Deciding factor beyond the initial pros/cons: Option D (LiteLLM's Rust
gateway) is the intended long-term destination once it's released and
proven stable, and Option B migrates onto it with zero code changes — swap
`base_url` from Ollama's/OpenRouter's endpoint to the gateway's, delete the
now-redundant Anthropic adapter. Option A (`litellm` Python SDK) does not
migrate onto Option D cleanly despite the shared name — `litellm.completion()`
is a different call convention than OpenAI-shaped HTTP against a
`base_url`, so choosing A now would mean throwaway integration work once
the gateway ships, re-deriving what B already provides. Choosing B now
means today's minimal-footprint choice and the eventual migration path are
the same choice, not a tradeoff between them.

## Consequences

### Positive
- Minimal dependency footprint in the `api` process — just the official
  `openai` SDK, no `tiktoken` or unrelated provider integrations.
- Ollama and OpenRouter support requires no custom parsing — both are
  OpenAI-API-compatible, so it's a `base_url`/`api_key` configuration
  difference, not new code.
- Clean, zero-rewrite migration path to Option D (LiteLLM's Rust gateway)
  once it ships and is stable — this decision doesn't get revisited as a
  mistake later, only extended.
- Matches the SDK-based-but-minimal pattern already accepted in this
  project before (`openai>=1.0` was a real dependency prior to the
  Graphify replacement, ADR-013).

### Negative
- Anthropic support requires hand-writing and maintaining a small adapter
  mapping Anthropic's native message/response shape onto this module's
  internal `ChatMessage`/`ChatResponse` model — real, one-time work, not
  automatic.
- No built-in retry/backoff for cloud-API-specific failures (rate limits,
  transient 5xxs) — must be written explicitly, reusing
  `prisma.services.backoff`'s exponential-backoff-with-jitter primitive but
  wired to HTTP status codes rather than its current trigger (waiting for
  a local GPU pool slot to free).
- No automatic cross-provider fallback routing (e.g., "try Ollama, fall
  back to cloud") — not needed today, but would be fully hand-rolled if
  wanted later, unlike Option A/D.

## Appendix — tool-calling reliability test (2026-07-02)

Separately from this ADR's own scope, a related question came up while
designing the chat module's tool loop (`TODO.md`): would `pydantic-ai`'s
native-function-calling-based agent loop be worth adopting instead of the
hand-rolled pattern-based tool-call convention `TODO.md` already assumed?
Rather than decide on the assumption alone, ran a disposable 5-prompt
comparison against `qwen2.5:7b` (the realistic local chat-model stand-in —
`llama3.1:8b` isn't actually pulled despite `installation.md` naming it
default): Ollama's native `/api/chat` `tools` param vs. a hand-written
pattern prompt + regex, same two stub tools (`search_vault`,
`graph_context`) both ways.

| Prompt | Expected | Native tool-calling | Pattern-based |
|---|---|---|---|
| "attention mechanisms in my notes" | `search_vault` | ✅ `search_vault` | ✅ `SEARCH_VAULT` |
| "sparse autoencoders relate to interpretability" | `graph_context` | ❌ called `search_vault` (wrong tool) | ✅ `GRAPH_CONTEXT` |
| "Hi, how are you today?" | no tool | ✅ no tool | ✅ no tool |
| "What does LLM stand for?" | no tool (model knows this) | ❌ called `search_vault` (unnecessary) | ✅ answered directly |
| "Tell me something interesting" (ambiguous) | either defensible | called `search_vault` | answered directly (defensible) |

**Result: pattern-based 4/5 clean vs. native tool-calling 2/5 clean** — native
picked the wrong tool for a clearly relational question, and over-triggered
a vault search for something the model already knew unprompted (an
unnecessary Ollama round-trip competing for the shared GPU pool, for no
benefit). This confirms — rather than just assumes — that the
pattern-based approach is the right default for the current 7B-class local
model. `pydantic-ai` remains worth revisiting once a more capable model
(larger local model, or a cloud backend under this ADR's Option B/D) is the
default chat backend — cloud models are typically far more reliable at
native tool-calling, and `pydantic-ai` supports custom OpenAI-compatible
`base_url`s, so it would compose fine with this ADR's decision if adopted
later for a backend where native tool-calling actually holds up. Full
finding also recorded in `TODO.md`'s chat module section, where it directly
informs the tool-loop design.

## Related ADRs

- ADR-012: Process Supervision (compute-pool leasing; `model_affinity:
  false` pools are how cloud-backed chat calls avoid the local-GPU
  arbitration model built for Ollama)
- ADR-013: Native Knowledge Graph (the existing direct-`requests`-to-Ollama
  pattern this ADR deliberately does not repeat for chat)
