# OpenRouter free-tier models vs. the FOOTNOTES_JSON protocol

Context: switching local dev's `[chat]` provider from local llama-swap
(`qwen2.5-3b`) to OpenRouter/`gpt-4o-mini`, matching forge's deployed config,
after live testing on the chat-schema-v3 PR surfaced qwen2.5-3b unreliably
following ADR-017's citation protocol (marker text with no backing
`FOOTNOTES_JSON` trailer at all). Before committing to `gpt-4o-mini` as a
paid dependency for local dev, worth checking whether any of OpenRouter's
`:free` models could stand in for it. Run 2026-08-18.

## Method

Same methodology precedent as `docs/kg-extraction-context-length.md` ("called
directly against Ollama — bypassing resource_lock/the supervisor, a single
sequential script"): a harness calls OpenRouter directly via the `openai`
SDK, using Prisma's exact real system prompt — pulled live from
`chat_prompts.load_system_prompt()` + `chat_tools.system_prompt_tool_section()`
+ `system_prompt_footnote_section()`, not approximated — plus a scripted
`SEARCH_VAULT` tool response in place of a real vault, so every model is
tested against identical "ground truth" content.

Three scenarios, one call each per model:

| Scenario | Question | Tool result |
|---|---|---|
| `single_source_match` | MEMIT paper question | one clean matching source |
| `no_results_found` | small-RAM LLMs question | `(no results found)` — the real bug-report scenario |
| `multi_source_relational` | ROME vs. MEMIT comparison | two related sources |

One subagent per model, run in parallel, each executing the harness against
one OpenRouter model ID and reporting a structured JSON result: markers
found, `FOOTNOTES_JSON` trailer present/valid, marker↔trailer entry count
match, tool calls made, elapsed time, error.

Models tested: `openai/gpt-4o-mini` (paid control), `nvidia/nemotron-3-super-120b-a12b:free`,
`google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `z-ai/glm-5.2:free`,
`nvidia/nemotron-3-nano-30b-a3b:free`, `openai/gpt-oss-20b:free`,
`liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-nano-9b-v2:free`,
`nvidia/nemotron-3-ultra-550b-a55b:free`.

`harness.py` and each model's raw JSON result (`results/`) live alongside this
file for reproducibility — rerun with
`OPENROUTER_API_KEY=... python3 harness.py --model <id> --out results/<slug>.json`.

## Round 1: a false start (harness didn't match the real system)

First pass produced a "stuck in a loop" finding for `nemotron-nano-9b` and
generally erratic results. Before trusting any of it, checked the harness
against `ChatAgent.respond()`'s actual behavior (`prisma/agents/chat_agent.py`)
and found three mismatches:

1. **`MAX_TOOL_ITERATIONS = 3` in the harness vs. the real `= 4`**
   (`chat_agent.py:30`) — directly caused the false "stuck in loop" finding
   for `nemotron-nano-9b`'s no-results scenario; it hadn't actually looped
   forever, it just hit a cap one iteration too early.
2. **`temperature` never set** — the harness's `client.chat.completions.create()`
   call omitted it, silently defaulting to the API's own ~1.0, vs. the real
   `ChatLLM.complete()`'s default of `temperature=0.1` (`self._llm.complete(messages)`
   in `chat_agent.py:310` passes no override, so `complete()`'s own default
   parameter applies).
3. **`timeout=90` vs. the real `timeout=180.0`** — the `OpenAI` client's
   instance-level default set in `ChatLLM.__init__`.

Temperature affects every single completion, not just iteration-limited
cases, so all 9 free models plus the control were re-run from scratch after
fixing all three. The control model alone showed materially different
results before/after the fix (different scenarios failing at ~1.0 vs. 0.1),
confirming the first pass wasn't trustworthy.

## Round 2: corrected results

| Model | single_source_match | no_results_found | multi_source_relational |
|---|---|---|---|
| `gpt-4o-mini` (control) | ✅ 2.8s | ❌ no trailer, 5.1s | ❌ skipped tool call, 5.1s |
| `nemotron-3-super-120b` | ✅ 7.3s | ✅ 6.6s | ❌ malformed trailer, 8.6s |
| `gemma-4-31b` | 429 rate-limited | 429 rate-limited | 429 rate-limited |
| `gemma-4-26b` | ❌ leaked fake tool syntax, 2.3s | ❌ same, 2.0s | ✅ 18.0s |
| `glm-5.2` | 429 rate-limited | 429 rate-limited | 429 rate-limited |
| `nemotron-3-nano-30b` | ✅ 7.6s | ⚠️ fabricated, 15.1s | ⚠️ skipped tool, fabricated, 4.9s |
| `gpt-oss-20b` | ❌ empty completion, 3.3s | ❌ empty, 6.5s | ❌ empty, 10.3s |
| `lfm-2.5-2.6b` | ❌ leaked native tool tokens, 0.7s | ❌ same, 1.4s | ❌ same, 2.5s |
| `nemotron-nano-9b` | ✅ 24.5s | ❌ phantom footnote, 41.8s | ❌ phantom footnote, 35.6s |
| `nemotron-3-ultra-550b` | ❌ loop, 434.3s | ❌ loop, 167.6s | ✅ 131.8s |

✅ = markers present, trailer present, valid JSON, entry count matches marker
count. ❌ = protocol violated in some way. ⚠️ = protocol-compliant but a real
faithfulness concern (see below). 429 rows are infra-level rate limiting on
OpenRouter's shared free-tier pool for that provider, not a model-quality
result.

### Per-model notes

**`gpt-4o-mini` (control)** — 1/3 clean. Failed to emit a trailer in
`no_results_found` despite calling the tool, and skipped the tool call
entirely in `multi_source_relational`, answering from training knowledge
with zero markers. At n=1 trial per scenario this is as much sampling noise
at `temperature=0.1` as a real weakness, but it matters for the study: even
the paid model we're using as ground truth isn't a clean 3/3 on a single
run, so no free model should be held to a stricter bar than that.

**`nemotron-3-super-120b`** — 2/3 clean, and the one case across the whole
study of a model correctly declining to fabricate: in `no_results_found` it
labeled its general-knowledge claims with `sources: []` instead of inventing
a source. The one failure (`multi_source_relational`) was a near-miss, not a
protocol violation — the `FOOTNOTES_JSON` was valid JSON but pretty-printed
across multiple lines instead of one, and the line-anchored trailer regex
(matching Prisma's real parser) doesn't match a multi-line JSON blob.

**`gemma-4-31b`** — inconclusive. `RateLimitError 429` on all three
scenarios, both the first and corrected runs — Google AI Studio's shared
free pool was saturated throughout testing, not a finding about the model.

**`gemma-4-26b`** — leaked fake tool-call syntax as literal text
(`<|tool_call|>call:SEARCH_VAULT: ...`) instead of using the marker
protocol on two of three scenarios. Only clean on the one scenario that
didn't require a tool call. Note: the 347-marker runaway repetition loop
seen in the *first* (buggy, high-temperature) run did not reproduce at
`temperature=0.1` — a genuine improvement from the harness fix, not just
noise.

**`glm-5.2`** — inconclusive. `RateLimitError 429` on all three scenarios
(provider "Decart"'s shared pool), both attempts.

**`nemotron-3-nano-30b`** — format-mechanically perfect 3/3 (markers,
trailer, valid JSON, matching counts), but a real faithfulness problem in
two of three: in `no_results_found` it confidently fabricated specific
technical content (quantization techniques, model names) under `sources: []`
rather than clearly stating nothing was found, and in
`multi_source_relational` it skipped the tool call entirely, answering from
training knowledge with empty sources on every claim. Protocol-compliant,
not trustworthy.

**`gpt-oss-20b`** — completely empty completions (`raw_reply: ""`) on all
three scenarios, no error, no tool call. Reproduced identically on both the
buggy and corrected runs, so this isn't a temperature artifact — genuinely
non-functional on the free tier as tested.

**`lfm-2.5-2.6b`** — leaks native function-calling special tokens as literal
text on every scenario
(`<|tool_call_start|>[SEARCH_VAULT(...), RECALL(...)]<|tool_call_end|>`).
Reproduced identically on both runs. This model was trained for native
tool-calling and has no fallback to plain-text instructions — a fundamental
architecture mismatch with Prisma's marker-based protocol (ADR-014), not a
quality issue that temperature or prompting could fix.

**`nemotron-nano-9b`** — a distinct failure mode not seen elsewhere:
"phantom footnotes." In both `no_results_found` and `multi_source_relational`
it wrote a fully valid `FOOTNOTES_JSON` trailer with zero `[^N]` markers
anywhere in the text — trailer entries with nothing to attach to. Fixing the
original iteration-cap harness bug didn't make this model reliable, it just
revealed a different failure underneath.

**`nemotron-3-ultra-550b`** — slow and unreliable. 1 of 3 scenarios
succeeded cleanly (`multi_source_relational`, 131.8s); the other two got
stuck repeatedly re-calling `SEARCH_VAULT` without ever producing a final
answer, hitting the 4-iteration cap at 167.6s and 434.3s respectively. Even
the one working case took over two minutes. See Round 3 below — the first
attempt at `single_source_match` crashed the harness itself, which briefly
looked like a fourth distinct failure mode before being traced to a harness
bug, not a model bug.

## Round 3: a harness robustness gap, found live

Mid-study, `single_source_match` against `nemotron-3-ultra-550b` threw
`TypeError: 'NoneType' object is not subscriptable` from this line:

```python
reply = resp.choices[0].message.content or ""
```

OpenRouter can return HTTP 200 with an empty or missing `choices` list — an
upstream provider-level error wrapped in a non-standard body — instead of a
proper `APIError`. The `openai` SDK doesn't catch this case; it parses
`resp.choices` as `None`, and indexing `[0]` throws. The harness's
`try/except Exception` around the whole call *did* catch the `TypeError`, so
nothing crashed the study, but the recorded error was just the bare
`TypeError` text — no way to tell from it whether this was the model failing
or OpenRouter's routing failing at the transport level.

Fixed by checking for an empty `resp.choices` explicitly and capturing the
raw response body when it happens, instead of letting a confusing `TypeError`
stand in for a real diagnosis:

```python
if not resp.choices:
    error = f"empty response (no choices) from OpenRouter: {resp.model_dump_json()}"
    break
```

Re-running just `single_source_match` for `nemotron-3-ultra-550b` under the
fixed harness resolved the ambiguity: it wasn't a transport-level fluke, the
model got stuck in the same iteration-cap tool-call loop seen in the other
two scenarios (434.3s). The original `TypeError` had been masking a real
model failure, not manufacturing a fake one — but that wasn't knowable until
the harness could actually distinguish the two cases.

## Cross-model patterns

- **`no_results_found` was disproportionately hard, across nearly every
  model tested — including the paid control.** `gpt-4o-mini` itself failed
  to emit a trailer here. This suggests the "nothing found" case may be a
  gap in Prisma's own prompt engineering (the system prompt doesn't give
  explicit guidance for what to do when a tool call returns nothing), not
  purely model-capability variance.
- **Native-function-calling-trained free models leak their own special
  tokens as plain text** (`gemma-4-26b`, `lfm-2.5-2.6b`) instead of using
  Prisma's marker protocol. This is an architecture mismatch, not a quality
  problem — no amount of prompting fixes a model emitting tokens its
  tokenizer treats as structural rather than textual.
- **Format-perfect isn't the same as faithful.** `nemotron-3-super-120b`
  and `nemotron-3-nano-30b` both produce syntactically valid
  `FOOTNOTES_JSON` most of the time, but only the former reliably declines
  to fabricate when nothing is found — the latter confidently invented
  specific technical claims under `sources: []`.
- **A distinct "phantom footnote" failure mode exists** (`nemotron-nano-9b`):
  a valid trailer with entries that don't correspond to any `[^N]` marker in
  the text. Prisma's real parser (`chat_agent.py`'s `_extract_claims`) has no
  specific handling for this — worth checking separately whether it silently
  drops the orphaned entries or does something worse.

## Conclusions

1. **No free model tested is an unambiguous drop-in replacement for
   `gpt-4o-mini`.** Every one failed at least one scenario outright, and two
   (`gemma-4-31b`, `glm-5.2`) never got a real trial due to persistent
   upstream rate-limiting.
2. **`nemotron-3-super-120b` is the strongest candidate**, if this were
   revisited later — 2/3 clean, and the only model observed correctly
   declining to fabricate when nothing was found. Still "shaky" at n=1 trial
   per scenario, and its one failure (multi-line JSON) might be a one-line
   fix on Prisma's parser side (accept pretty-printed trailer JSON) rather
   than a model problem — not pursued here since it wasn't the goal of this
   study.
3. **`nemotron-3-ultra-550b` is impractical regardless of quality** — up to
   434s for a single reply on the free tier, close to the 180s per-call
   timeout on two of three calls it needed to make. Not a serious option
   even before considering correctness.
4. Local dev's config stays on OpenRouter/`gpt-4o-mini`, matching forge — no
   change resulting from this study. This was mainly a due-diligence check
   before committing to a paid dependency for local dev, not a search that
   was expected to find a free replacement.

## Applied

No code or config change — `~/.config/prisma/config.toml`'s `[chat]`/`[llm]`
already point at `openrouter`/`openai/gpt-4o-mini` (see the header comment
in that file for the switch's original rationale). The one real code
artifact from this investigation is the harness robustness fix in Round 3,
which lives only in the throwaway test script, not in Prisma itself —
`ChatLLM`'s real OpenAI-SDK call site should be checked separately for the
same `resp.choices` empty-list gap, since the same OpenRouter behavior could
in principle hit production, not just this harness.
