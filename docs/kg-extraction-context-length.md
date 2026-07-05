# kg extraction quality vs. input length

Controlled test of whether `qwen2.5:7b-32k`'s knowledge-graph extraction
quality degrades as the input section grows — run 2026-07-02 after noticing
garbled/stray entities on a real paper (`Meng_2023_MEMIT_Mass_Editing_Memory.md`:
a hallucinated `EMIX` node, stray `Star Constellations`/`Percy Snow` entities
pulled from the paper's own illustrative examples rather than its real
content). Motivation: confirm or rule out context length as a cause before
changing anything, rather than guessing.

## Method

A fixed ~1.2k-token target section (the MEMIT paper's title/abstract/intro —
rich in real, manually-verifiable entities: MEMIT, ROME, GPT-J, GPT-NeoX,
authors, institutions) is always placed at the **start** of the input. Three
levels pad it with increasing amounts of unrelated real text (Vaswani et
al.'s "Attention Is All You Need") appended after it, so the target's
*position* is held constant across all three levels and only total length
varies — isolating a length/dilution effect from a position effect ("lost in
the middle").

Same system prompt (`_EXTRACTION_SYSTEM`) and injection-defense wrapping
(`wrap_untrusted`) prisma's real `KnowledgeGraphService` uses, called
directly against Ollama — bypassing `resource_lock`/the supervisor, a single
sequential script, not testing concurrency (same methodology as
`docs/ollama-concurrency.md`).

## Round 1: a false alarm (real bug, not a quality issue)

First pass, *without* `format: "json"` on the Ollama request:

| Level | ~tokens | elapsed | nodes | edges |
|---|---|---|---|---|
| A (target only) | 1,262 | 30.5s | 26 | 18 |
| B (target + padding) | 8,000 | 12.6s | **0** | **0** |
| C (target + padding) | 11,010 | 25.9s | **0** | **0** |

B and C looked like total collapse. Inspecting the raw response showed why:
the model wrapped valid, good-quality JSON in ` ```json ... ``` ` markdown
fences — which the system prompt explicitly forbids, but the model did it
anyway on the longer inputs — and `_parse_extraction_response()` didn't strip
fences before `json.loads()`, so a perfectly good extraction was silently
discarded as "found nothing." This was a real, previously-unnoticed
production bug (any section long enough to trigger fence-wrapping lost its
entire extraction silently), not evidence of the model's recall failing.

Two fixes applied:
1. `_parse_extraction_response()` now strips a leading/trailing ` ``` ` (or
   ` ```json `) fence before parsing — cheap defensive parsing, not
   model-specific (fence-wrapped JSON is common across most instruction-tuned
   LLMs, not a quirk unique to this one).
2. `_call_ollama_extract()` now passes `"format": "json"` to
   `/api/generate` — Ollama's actual structured-output feature, which forces
   valid JSON at the grammar level instead of relying on the system prompt's
   instruction (which the model was ignoring at longer inputs). This is the
   real fix; the fence-strip is just a defensive backstop.

## Round 2: the real signal, with `format: "json"` applied

| Level | ~tokens | elapsed | nodes | edges | notes |
|---|---|---|---|---|---|
| A (target only) | 1,262 | 41.7s | 13 | 9 | clean — all real, on-topic entities (MEMIT, ROME, authors, institutions), no duplicates |
| B (target + padding) | 8,000 | 87.1s | 29 | **5** | duplicates: `Wang & Komatsuzaki 2021` ×3, `Petroni et al. 2020` ×2, `Black et al. 2022` ×2; more raw nodes but *fewer* real relationships found |
| C (target + padding) | 11,010 | 44.0s | 8 | 6 | collapses back down; one hallucinated/garbled label: `"MEMIT meditation"` |

This is the real, previously-hidden signal (Round 1's `format: "json"`-less
results couldn't show it because B/C were silently zeroed out). Quality does
measurably degrade with input length, but not as raw failure — it shows up
as **duplicate/redundant entity emission** and **fewer relationships
extracted per unit of content**, with occasional **garbled entity names**
appearing at the longest length tested. Our production `token_budget=8000`
sits right at level B, already inside the zone where this shows up.

## Round 3: does a smaller model do just as well? (`qwen2.5:3b-instruct-q4_K_M`)

Pulled fresh from the Ollama library. First pitfall, worth flagging on its
own: the stock tag's runtime `context_length` defaulted to **4096**, not the
model's architectural ceiling (`qwen2.context_length: 32768` per
`/api/show`) — confirmed via `/api/ps` after load. This is the same
configured-vs-enforced trap documented in ADR-013's follow-up section, just
on a different model: checking the architecture's max via `/api/show` is not
the same as checking what Ollama actually loaded the runner with. The first
attempt at levels B/C (8k/11k tokens) silently produced garbage against the
real 4096-token window; re-run with an explicit `options.num_ctx: 32768`
override to match `qwen2.5:7b-32k`'s real deployed setting fairly.

With that correction (`format: "json"` + explicit `num_ctx: 32768`):

| Level | ~tokens | 3B elapsed | 3B nodes/edges | 7B elapsed | 7B nodes/edges |
|---|---|---|---|---|---|
| A | 1,262 | 127.1s | 9 / 20 | 41.7s | 13 / 9 |
| B | 8,000 | 28.0s | 5 / 4 | 87.1s | 29 / 5 |
| C | 11,010 | **timed out at 600s, no result** | — | 44.0s | 8 / 6 |

Two clear problems, not just "somewhat lower quality":

- **Level A took 3x longer than the 7B model** (127s vs 42s) for the
  identical short prompt — plausibly a one-time backend warm-up cost from
  allocating a fresh 32768-token KV cache, but still a real cost observed on
  the first real request after load.
- **Level C never finished.** GPU utilization stayed low the whole time
  (consistent with normal memory-bound autoregressive decoding, not
  evidence of a hang by itself), but after 10 minutes the request was still
  running with nothing to show for it — at the exact input length the 7B
  model handled cleanly in 44s. Read as the 3B model getting stuck in a
  long or degenerate generation trying to satisfy the `format: "json"`
  grammar constraint at this input length — a real reliability failure, not
  just lower quality.

Also notable at level A: 20 edges for only 9 nodes is a high edges-per-node
ratio compared to the 7B model's 9-nodes-to-13 at the same level — plausibly
duplicate or spurious relations, not inspected in detail since level C's
outright failure already settled the comparison.

## Round 4: does a smaller `num_ctx` (8192 vs 32768) fix or change things?

Same target+padding methodology, both models, but `num_ctx=8192` (4x smaller
than production) with proportionally smaller content levels so everything
still fits with headroom for the ~750-token system prompt and generation
(A=1,262 / B=4,000 / C=5,800 tokens — smaller than Round 2/3's B/C since a
much smaller context has much less room):

| Model | Level | ~tokens | elapsed | nodes | edges | notes |
|---|---|---|---|---|---|---|
| 7B | A | 1,262 | 74.6s | 21 | 14 | more entities than the 32768-ctx run at the same content (13/9), but ~1.8x slower — plausibly a one-time reload cost from switching context size, not a stable signal |
| 7B | B | 4,000 | 48.4s | 8 | 7 | |
| 7B | C | 5,800 | 41.7s | 5 | 4 | thinning out, consistent with the length-degradation pattern already seen |
| 3B | A | 1,262 | 44.3s | 6 | 5 | duplicate `MEMIT` node emitted twice |
| 3B | B | 4,000 | 21.0s | 4 | 3 | fast, but sparse |
| 3B | C | 5,800 | 42.7s | 10 | 9 | **hallucinated entities**: `Aaron Mitchell`, `Jeffrey Patterson` — these names don't exist anywhere in the source text; the real citations are "Mitchell et al. 2021" (MEND's authors) and "Patterson et al. 2021" — the 3B model appears to have invented plausible-sounding full first names for bare "et al." citations, which the 7B model never did in any run |

The good news: **no timeouts this time** — a smaller `num_ctx` avoided the
3B model's runaway-generation failure from Round 3's level C. The bad news:
smaller `num_ctx` doesn't fix the underlying quality patterns (still thins
out / gets noisier with length for the 7B model), and surfaces a new,
distinct failure mode for the 3B model — outright fabricating entity names
from bare citations, not just being sparse or duplicating. This is a step
below "lower quality" — it's actively wrong information asserted as fact,
worse for a knowledge graph that's supposed to be trustworthy.

## Round 5: real semchunk chunking, same content, different granularity

Rounds 1-4 used synthetic target+unrelated-padding to isolate a pure
length effect. This round instead chunks the *actual* MEMIT paper with
`semchunk.chunkerify()` — the real function `_extract_file` uses — at two
different `chunk_size` settings, to directly compare what production
actually does at `token_budget=8000` against a much smaller `token_budget`,
on identical real content:

- `chunk_size=8000` (current production `token_budget`): 3 chunks — sizes
  ~7,987 / 7,949 / 1,755 tokens.
- `chunk_size=2000`: 10 chunks — sizes ~1,912 / 1,920 / 1,992 / 1,993 / ...

For a fair comparison, the first big chunk (~7,987 tokens, covering roughly
the paper's first half) is compared against the first 4 small chunks
(~1,912+1,920+1,992+1,993 ≈ 7,817 tokens — covering essentially the same
span of real content), extracted with `qwen2.5:7b-32k`, `format: "json"`,
`num_ctx=32768` for the big chunk (matching the real production setting)
and `num_ctx=8192` for the small chunks (ample headroom for ~2k tokens of
content).

| Chunk | ~tokens | elapsed | nodes | edges | notes |
|---|---|---|---|---|---|
| Big (chunk_size=8000) | 7,987 | 58.4s | **6** | **9** | `MEMIT`, `ROME`, `MEND`, `SERAC`, `FT-W` + the paper itself — reasonable, but sparse for a span covering the abstract through several pages of related work and method |
| Small 0 (chunk_size=2000) | 1,912 | 44.1s | 15 valid + 2 malformed junk entries | 0 | `MEMIT/ROME/MEND/SERAC` again, plus real detail the big chunk missed entirely (GPT-J/GPT-NeoX parameter counts, "Knowledge-Editing Methods", "Knowledge Bases") — but 0 edges is a real miss, and 2 stray junk nodes appeared (one with `id: null`, one that was literally the string `"file_type: "` — malformed output surviving `format: "json"`'s validity check while still violating the schema) |
| Small 1 | 1,920 | 128.9s | 20 | 19 | rich, specific citation-level detail (Elhage 2021, Dar 2022, Geva 2021/2022, Pearl 2001, etc.) — exactly the kind of "Related Work" paragraph citation network a KG should capture, that the big chunk skipped entirely |
| Small 2 | 1,992 | 46.4s | 13 | 7 | covers a dense equation-heavy passage — extracted nodes here are noisier/lower-value (`W0`, `W1`, `K0`, `M0`, `K1`, `M1`, `C0`, `R` — these are the paper's own mathematical notation variables, not meaningful standalone knowledge-graph entities) |
| Small 3 | 1,993 | 79.9s | 12 | 11 | clean — `MEMIT Algorithm`, `GPT-J (6B)`, `GPT-NeoX (20B)`, baselines, datasets (zsRE, CounterFact), citations |
| **Small total** | 7,817 | **299.3s** | **59 unique** (60 raw, 2 junk excluded, 1 real duplicate) | **37 unique** (37 raw, zero duplication) | |

This is the clearest result of the whole investigation. For essentially the
same span of real content, the small-chunk approach found **~10x more
unique, real entities** (59 vs 6) and **~4x more relationships** (37 vs 9),
with duplication that's nearly nonexistent (1 real duplicate id across 4
independent calls, plus 2 malformed junk entries — not the systematic
same-entity-3x-in-one-response duplication seen in Round 2's single 8k-token
call). The one real downside besides raw time: very dense, equation-heavy
passages (Small 2) produce noisier, lower-value nodes (mathematical notation
treated as entities) regardless of chunk size — that's a prompt-tuning
problem, not a chunk-size one.

The time cost is real but likely overstated by this test's methodology:
these 4 calls ran **sequentially** (299.3s total) to isolate per-call
behavior cleanly, but they're 4 sections of the *same file*, which
`_extract_file`'s existing `ThreadPoolExecutor` fan-out already runs
**concurrently** in production (see `knowledge_graph_service.py`). Run
concurrently, the effective wall-clock cost approaches the slowest single
call (~129s) rather than the summed 299.3s — still slower than the big
chunk's single 58.4s call, but not by 5x, and in exchange for dramatically
richer, cleaner extraction. That concurrency benefit currently depends on
`kg.extraction_concurrency`/`background_max_concurrent`, both of which were
turned down to 1 earlier this session to fight GPU contention — worth
revisiting together once `token_budget` is actually lowered, since a
smaller `token_budget` directly reduces the per-call latency that motivated
dropping concurrency to 1 in the first place.

## Conclusions

1. **`format: "json"` is a required fix, not optional** — without it, longer
   sections can silently lose their entire extraction to fence-wrapping.
   Applied in `knowledge_graph_service.py`.
2. **Context length does measurably hurt quality** in this deployment, past
   roughly 1-2k tokens of real content — the failure mode is duplication and
   relationship under-extraction, not simply "fewer nodes."
3. **`token_budget=8000` is confirmed too generous — this is now the
   strongest, most actionable finding of the whole investigation.** Round 5
   tested this directly on real content (not synthetic padding): the same
   ~7,800 tokens of the actual MEMIT paper produced **6 nodes/9 edges** as
   one big chunk vs **59 unique nodes/37 unique edges** as four ~2k-token
   chunks — roughly 10x more real entities and 4x more relationships, with
   almost no duplication. `token_budget=8000` was raised from 1500 (see
   ADR-013's follow-up section) specifically to reduce call *count* per
   file — this data says that traded away most of the graph's actual value
   to get there. **Lowering `token_budget` to roughly 2000 is the single
   highest-leverage change available**, ahead of any model or architecture
   change.
4. **The wall-clock cost of smaller chunks is real but not as bad as
   4-calls-vs-1 sounds**, because `_extract_file` already fans out a file's
   sections concurrently — the 299.3s *sequential* total for 4 small chunks
   in Round 5 would collapse toward the slowest single call (~129s) if run
   concurrently as production actually does. That concurrency currently
   depends on `kg.extraction_concurrency`/`background_max_concurrent`, both
   turned down to 1 earlier this session to fight GPU contention from
   `token_budget=8000`-sized calls — revisit that setting once
   `token_budget` is actually lowered, since smaller calls are exactly what
   make raising concurrency safe again (shorter individual holds on the
   GPU, per-call latency dropping is what makes room for more of them).
5. **A smaller model is not a free win.** `qwen2.5:3b-instruct-q4_K_M`
   didn't just score lower — it outright failed to complete (600s timeout)
   at the same input length the 7B model handled without issue at full
   `num_ctx`, and even once a smaller `num_ctx` fixed that specific timeout,
   it introduced a new, worse failure mode: fabricating entity names
   (`Aaron Mitchell`, `Jeffrey Patterson`) that don't exist anywhere in the
   source text, apparently inventing plausible-sounding full names for bare
   "et al." citations. This rules out "swap to a faster model" as a cheap
   latency fix; the 7B model stays.
6. A GLiNER-style two-tier pipeline (small NER model + LLM only for
   relations) remains a valid *architectural* direction if quality issues
   persist after tuning `token_budget`, but per #3 above, it's very unlikely
   to be needed next — `token_budget` tuning at the current 7B model already
   produced a 10x quality improvement on real content, for free, with no
   new dependency.

## Applied

`token_budget` is now wired to `config.yaml`'s `kg:` section (it wasn't
before — only `extraction_concurrency` was; `token_budget` was a
constructor-only default) via a new `_token_budget()` helper in
`kg_app.py`, mirroring the existing `_extraction_concurrency()` pattern.
Set to **2000** in both `~/.config/prisma/config.yaml` and
`KnowledgeGraphService.__init__`'s default, per Round 5's finding. Requires
a `kg` worker restart (not a full `prisma serve` restart) to take effect —
not yet restarted as of this writing since the whole investigation ran with
`prisma serve` stopped.

Consider re-testing 3000-4000 as a middle ground if 2000 produces too many
calls per file in practice. Separately, once real production runs confirm
`token_budget=2000`'s actual per-call latency, revisit
`background_max_concurrent`/`kg.extraction_concurrency` (currently 1) —
shorter per-call latency at a smaller `token_budget` is exactly what makes
raising concurrency safe again without returning to the GPU contention that
motivated dropping it to 1.

## Follow-up (2026-07-05): lowered again to 1000, plus max_tokens and stop-on-failure fixes

Live extraction (not this doc's controlled test — real production traffic
against the actual vault) hit a case this investigation didn't cover: a
Chinchilla-scaling-laws paper's chunk produced JSON long enough to exceed
`_call_ollama_extract`'s `max_tokens=2000` cap, got truncated mid-object,
and failed validation permanently (Instructor treats a length-truncated
response as immediately fatal — `IncompleteOutputException`, not
retryable, since retrying at the same cap just truncates again the same
way). Two changes, per cservinl:

1. **`max_tokens` raised 2000 → 4000** in `_call_ollama_extract` — the
   original assumption ("extraction JSON shouldn't need to be longer than
   the section it's summarizing") doesn't hold for entity-dense papers.
2. **`token_budget` lowered 2000 → 1000** (this doc's own default) — same
   direction as Round 5's finding, on the theory that smaller input
   sections produce proportionally smaller (less truncation-prone) output.
   Not yet its own controlled test — worth re-running Round 5's method at
   1000 if this doesn't hold up in practice.

Separately, a dropped chunk used to leave its file in an ambiguous state —
`all_ok=False` meant the file's indexed hash was never advanced, so it
would *eventually* be retried (next full index or real edit), but nothing
proactively re-queued it. `_extract_file` now: stops the rest of that
file's sections the moment one fails (a bounded sliding-window submission,
not a naive cancel-in-flight — see its own docstring for why the naive
version was a real race, not just a hypothetical one), records the failure
to a small dead-letter queue (`kg-out/dead_letters/*.txt`, the actual
failed chunk text plus why it failed — `truncated`/`invalid`/`connection`),
and adds the file straight to `self._pending` so the next background cycle
(≤60s) retries it, instead of waiting on a real edit or a full restart.
