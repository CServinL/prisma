# Qwen3 family evaluation — kg extraction, tool-calling, and summarization

Rigorous, measured re-run of every controlled test this project has already
run against `qwen2.5:7b-32k` (`docs/kg-extraction-context-length.md`,
`docs/ollama-concurrency.md`, ADR-014's tool-calling appendix) plus a net-new
chat-summarization check, against four Qwen3-generation candidates. Trigger:
an unsourced secondhand claim that Qwen3-14B has "incredibly low validation
error rates" on strict schemas like Pydantic — worth checking against real
evidence rather than trusting, since Instructor's whole mechanism (ADR-016)
is exactly that kind of validation. Hardware: RTX 4090M laptop GPU, 16GB
dedicated VRAM, `vram_budget_mb: 14000` configured.

Candidates tested: `qwen3:14b`, `qwen3.6:27b`, `qwen3:30b-a3b` (MoE), and
`qwen3.5:9b`. All four real-time, live-measured — no simulated numbers.

## Step 0/1: VRAM fit and real context window

| Candidate | Params | Quant | VRAM @ ctx=32768 | GPU/CPU split | Verdict |
|---|---|---|---|---|---|
| `qwen2.5:7b-32k` (current) | 7.6B dense | Q4 | ~7.5GB | 100% GPU | baseline |
| `qwen3:14b-32k` | 14.8B dense | Q4_K_M | ~11.9GB | 100% GPU | fits, tight headroom (~1.8GB vs. current's ~6.2GB) |
| `qwen3.5:9b-32k` | 9.7B dense | Q4_K_M | ~9.2GB | 100% GPU | fits well (~4.5GB headroom) |
| `qwen3.6:27b` | 27.8B dense | Q4_K_M | 23GB total | **47%/53% CPU/GPU** | **fails** — doesn't fit, real partial offload |
| `qwen3:30b-a3b` (MoE, instruct-2507) | 30.5B (~3B active) | Q4_K_M | 22GB total @ ctx=32768 | **42%/58% CPU/GPU** | **fails fit**, but see below — didn't behave like a normal failure |

All four candidates ship with a default `context_length=4096` regardless of
architecture — the same "configured vs. enforced" trap this project has now
hit three times (ADR-013's follow-up, kg-extraction-context-length.md Round
3, and here). All were rebuilt with `PARAMETER num_ctx 32768` and
re-verified via `/api/ps` before any further testing, same as
`qwen2.5:7b-32k`'s own setup.

`qwen3.6`'s entire dense tag lineup is 27B+ (nothing between 2B and 27B) —
genuinely nothing on this hardware to test at this generation. `qwen3.5`'s
dense lineup does include a 9B tier (initially missed in a filtered registry
scan), which turned out to be the best-fitting candidate of the four.

### The MoE surprise (and why it still failed)

`qwen3:30b-a3b` doesn't fit VRAM (42%/58% split) but was **fast on a
trivial completion** — 24.7 tokens/sec on a 150-token "explain gradient
descent" prompt, faster than `qwen3:14b`'s fully-GPU ~10 tok/s. This matches
the architectural theory: MoE only activates ~3B params/token, so even with
most weights sitting on CPU, per-token compute stays low for a short,
simple prompt. That speed did **not** transfer to the real extraction
workload (see Step 3) — likely because a large, information-dense prompt
during prefill engages more of the partially-offloaded expert weights than
a 10-word prompt does.

## Step 2: Context-filling degradation (synthetic, `qwen3:14b` only)

Same methodology as `kg-extraction-context-length.md` Rounds 1-4 — real
MEMIT target section, increasing unrelated Vaswani-paper padding, target
position held constant.

| Level | `qwen2.5:7b` (Round 2 baseline) | `qwen3:14b-32k` |
|---|---|---|
| A (1,262 tok) | 41.7s, 13/9 nodes/edges, clean | 229.6s, 20/15, 0 retries |
| B (8,000 tok) | 87.1s, 29/5 — **duplicates** (3-4 entities repeated) | 436.1s, 22/22 — **zero duplicate IDs** |
| C (11,010 tok) | 44.0s, 8/6 — collapses, one hallucination | 1795.3s (~30 min), 25/26 — no collapse, started pulling entities from the *padding* text too |

Real, measured findings: `qwen3:14b` doesn't show `qwen2.5:7b`'s
rise-then-collapse quality pattern — counts climb steadily with length
instead, and duplication (a real, documented `qwen2.5:7b` weakness) doesn't
appear at all. But it's dramatically slower — 5.5×/5×/~41× slower at
levels A/B/C respectively.

## Step 3: Real extraction quality (the decisive test)

Same 3 real chunks (`Meng_2023_MEMIT_Mass_Editing_Memory.md`, chunked at
production `token_budget=1000` via the real `semchunk` call), run through
the actual `_call_ollama_extract`-equivalent Instructor pipeline, for a true
head-to-head — not loosely comparable historical numbers.

| | `qwen2.5:7b-32k` | `qwen3:14b-32k` | `qwen3-moe:30b` | `qwen3.5:9b-32k` |
|---|---|---|---|---|
| Avg latency (successful chunks) | **66.2s** | 258.3s (3.9×) | 389.7s (5.9×) | 70.8s (comparable) |
| Unique nodes | **47** | 37 | 30 | 24 (1 of 3 chunks) |
| Total edges | **46** | 37 | 39 | 20 (1 of 3 chunks) |
| Dropped chunks | 0 | 0 | **1 (timed out, 30 min)** | **2 of 3 (67%)** |

**`qwen3:14b`**: slower and lower-quality (fewer unique entities/edges) than
current production on identical content. Fails the adoption bar outright —
not a close call.

**`qwen3-moe:30b-a3b`**: worst performer of all four — slowest average
latency, fewest unique entities, and the only candidate with an outright
timeout/dropped chunk. The MoE speed advantage seen on trivial completions
did not hold up on the real, information-dense extraction task.

**`qwen3.5:9b-32k`**: root-caused, not just observed. It's a **hybrid-thinking
model** — confirmed directly: a native `/api/chat` call exposes a separate
`"thinking"` field consuming the bulk of `eval_count` (213 tokens total for
a 3-word visible answer to "what is 2+2"). The OpenAI-compat endpoint (what
Instructor actually uses) doesn't expose `thinking` separately — it just
counts toward `completion_tokens` — so a truncated response silently means
"still thinking, never got to the answer." Confirmed directly on a real
failing chunk: even with `think:false` passed via `extra_body` (which
*does* work for trivial prompts, 213→119 tokens), the same chunk against
the real long `_EXTRACTION_SYSTEM` prompt still burned **all 4000 tokens
with zero visible content** (`finish_reason=length`, empty `message.content`).
The "disable thinking" flag does not reliably hold once a long system
prompt is in play. **This is not a speed/quality tradeoff — it's an
unreliable call path for this specific task shape**, and not something
raising `max_tokens` further reliably fixes either (tested at 8000, one
chunk needed 7861 of the completion tokens just to produce a comparable-
scope answer to what `qwen2.5:7b` gets directly, meaning the visible
"extra" content wasn't actually extra extraction — it was overwhelmingly
invisible reasoning overhead, confirmed by inspecting the raw completion
directly rather than trusting parsed counts alone).

## Step 4: Concurrency (`qwen3:14b` only, `docs/ollama-concurrency.md` methodology)

3 sequential vs. 3 concurrent short calls (`num_predict: 150`), raw
`/api/generate`, bypassing `resource_lock`:

| | seq total | conc total | speedup |
|---|---|---|---|
| `qwen3:14b-32k` | 44.56s | 38.27s | 1.16× |

Identical speedup ratio to the original doc's `qwen2.5:7b` result at the
same `OLLAMA_NUM_PARALLEL=1`-equivalent default — concurrency behavior is
governed by Ollama's own parallel-request handling, not the model, as
expected. Not re-tested per-candidate since this doesn't vary by model.

## Step 5: Tool-calling reliability (`qwen3:14b` only, ADR-014 appendix methodology)

Same 5 prompts, same two stub tools, native `/api/chat` tools vs. the real
pattern-based convention (`chat_tools.py`'s actual system prompt + regex):

| Prompt | Expected | Native | Pattern |
|---|---|---|---|
| attention mechanisms in my notes | search_vault | ✅ search_vault | ✅ SEARCH_VAULT |
| sparse autoencoders relate to interpretability | graph_context | ❌ no tool | ❌ SEARCH_VAULT (wrong) |
| Hi, how are you today? | no tool | ✅ no tool | ✅ no tool |
| What does LLM stand for? | no tool | ❌ search_vault | ✅ no tool |
| Tell me something interesting | either defensible | search_vault | SEARCH_VAULT |

Pattern-based: 4/5 clean (same score as `qwen2.5:7b`, different specific
miss — `graph_context` confusion instead of the LLM-definition over-trigger).
Native: 2/5 clean (same score as `qwen2.5:7b`). No meaningful change either
way — the pattern-based convention's existing advantage holds.

## Step 6: Chat summarization quality (`qwen3:14b` and `qwen2.5:7b` only)

Real `ChatAgent.summarize()` call shape and real Excerpt-summary prompt,
against constructed pinned-turn content with 7 specific, checkable planted
facts (a decision, a rejected alternative, two numbers, three names).

| | `qwen2.5:7b-32k` | `qwen3:14b-32k` |
|---|---|---|
| Latency | **8.6s** | 34.2s (~4×) |
| Facts preserved | 5/7 — dropped both rejected alternatives | **7/7 — complete** |
| Faithfulness issue | Introduced a misattribution ("recommendation from the Chinchilla paper" — it wasn't a recommendation) | None observed |

**A genuine, measurable win for `qwen3:14b`** — complete fact preservation
vs. two dropped facts and a subtle hallucination, at a latency cost (34s)
that's real but far more tolerable than kg extraction's numbers, especially
given ADR-015's Excerpt regeneration already has an async
`excerpt_regenerating` UI state built to absorb exactly this kind of wait.

## Verdict

| Call site | Best candidate | Adopt? |
|---|---|---|
| kg extraction (`_call_ollama_extract`) | none of the four beat `qwen2.5:7b-32k` | **No** — stay on current model |
| Tool-calling (`ChatToolbox`) | no change either direction | **No change** — pattern-based stays default |
| Chat summarization (`ChatAgent.summarize()`) | `qwen3:14b-32k` | **Real win, but tried and reverted same day** — see below |

**Tried and reverted 2026-07-06.** `chat.model` was switched to
`qwen3:14b-32k` in `~/.config/prisma/config.yaml` to actually capture the
summarization win, separate from `llm.model`/kg's `qwen2.5:7b-32k`. Reverted
immediately once the consequence was worked through, not just measured in
isolation: `qwen2.5:7b-32k` (7500MB) + `qwen3:14b-32k` (11900MB) +
`nomic-embed-text` (1000MB) = 20400MB, well over this pool's 14000
`vram_budget_mb`. With kg extraction running continuously through a large
vault sync, that means an evict-and-reload cycle on *every* chat turn in
both directions — chat becomes effectively unusable while a sync is in
progress, a worse regression than the summarization win is worth.
`chat.model` is back to sharing kg's `qwen2.5:7b-32k`. Revisit once
supervisor can actually detect "these two configured models don't fit
together" before a config change ships — see `TODO.md`'s "supervisor
auto-profiles each configured model's real VRAM/GPU usage" entry, motivated
directly by this exact incident.

## Related

- `docs/kg-extraction-context-length.md` — the original `qwen2.5:7b`
  investigation this reuses methodology and baseline numbers from.
- `docs/ollama-concurrency.md` — concurrency methodology reused for Step 4.
- ADR-014 — tool-calling reliability appendix, reused for Step 5.
- ADR-015 — Excerpt/summarization model this evaluation's Step 6 targets.
- ADR-016 — Instructor adoption; the validation-error-rate claim that
  triggered this whole evaluation is directly about this mechanism.
- `TODO.md`'s "Deferred: try qwen3:14b for kg extraction" entry — resolved
  by this doc (kg: no; summarization: yes).
