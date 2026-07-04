# Ollama concurrency benchmark

Empirical test of how many concurrent calls a local Ollama instance can actually
absorb usefully, run against the real dev machine (WSL2, RTX 4090 laptop GPU,
16GB VRAM) to decide the `local-ollama` compute pool's `max_concurrent` in
`~/.config/prisma/config.yaml` (see ADR-012). Motivation: a single inference
call already under-uses the GPU for parts of its lifetime, but past some point
adding more concurrent calls only adds queueing/contention overhead rather
than real throughput — and mixing different models concurrently is a
different failure mode entirely (each swap evicts and reloads full weights).
This is not a general claim about all hardware — it's a measurement of one
machine, recorded so the `max_concurrent` setting is based on evidence rather
than a guessed number.

Method: `POST /api/generate`, same prompt (`num_predict: 150`), against
`qwen2.5:7b` and `qwen2.5-graphify:7b` — both already pulled locally. Sequential
calls run one after another; concurrent calls are fired at once via a thread
pool and use `requests` directly against Ollama (bypassing prisma's own
resource_lock/supervisor layer, to isolate Ollama's own behavior).

## Run 1 — `OLLAMA_NUM_PARALLEL=1` (default for this install)

Same model, 3 sequential vs. 3 concurrent calls:

| | seq-0 | seq-1 | seq-2 | total |
|---|---|---|---|---|
| elapsed_s | 1.45 | 1.83 | 1.32 | **4.60** |

| | conc-0 | conc-1 | conc-2 | total |
|---|---|---|---|---|
| elapsed_s | 2.63 | 3.96 | 1.46 | **3.97** |

Speedup: **1.16x**. Worse: individual latency got *less* predictable under
concurrency (worst case 3.96s vs. 1.83s sequential worst case) — because
Ollama queues requests internally when `n_seq_max=1`; the GPU only ever
executes one sequence at a time regardless of how many HTTP requests arrive
together. "3 concurrent" bought almost nothing beyond request-level overlap.

Alternating between 2 different models (`qwen2.5:7b` / `qwen2.5-graphify:7b`),
4 calls, sequential vs. concurrent:

| | seq (alternating) | conc (alternating) |
|---|---|---|
| total wall time | 20.98s | 12.71s |
| load_duration per call | ~4.0–4.1s (every call) | 0.2–5.3s (uneven) |
| eval_duration per call | ~0.95–1.03s | ~0.76–1.05s |

With `OLLAMA_MAX_LOADED_MODELS=1`, every model switch evicts the resident
model and reloads full weights (~4s), which dwarfs the ~1s of actual
generation. Concurrency helped total wall time somewhat here (overlapping
some of the reload waits), but the majority of time in both cases is pure
reload tax, not compute.

## Run 2 — `OLLAMA_NUM_PARALLEL=3`

Changed via a systemd drop-in (`/etc/systemd/system/ollama.service.d/override.conf`,
`Environment="OLLAMA_NUM_PARALLEL=3"`), confirmed in the runner logs
(`n_seq_max = 3` instead of `1` on model load).

Same model, 3 sequential vs. 3 concurrent calls:

| | seq-0 | seq-1 | seq-2 | total |
|---|---|---|---|---|
| elapsed_s | 1.40 | 1.87 | 1.41 | **4.68** |

| | conc-0 | conc-1 | conc-2 | total |
|---|---|---|---|---|
| elapsed_s | 2.33 | 2.31 | 2.33 | **2.34** |

Speedup: **2.00x**, and — unlike Run 1 — all three concurrent calls finished
in a tight, predictable band (2.31–2.33s) instead of a wide spread. This is a
real improvement: Ollama is now actually batching 3 sequences through the GPU
together rather than just queueing them behind a single execution slot.

Alternating between 2 different models, 4 calls, sequential vs. concurrent:

| | seq (alternating) | conc (alternating) |
|---|---|---|
| total wall time | 20.68s | 20.55s |
| load_duration per call | ~4.0–4.1s (every call) | 4.1–9.1s (worse under concurrency) |

Raising `OLLAMA_NUM_PARALLEL` did **not** help the mixed-model case at all —
if anything, concurrent mixed-model requests made reload contention worse
(some calls paid ~9s of load time instead of ~4s), since `OLLAMA_MAX_LOADED_MODELS=1`
still forces a single resident model regardless of how many parallel sequence
slots exist. Mixing models under concurrency is strictly worse than
serializing per model.

## Conclusions

1. **Same-model concurrency is real once `OLLAMA_NUM_PARALLEL` matches the
   pool's `max_concurrent`.** At `NUM_PARALLEL=1`, setting the prisma compute
   pool's `max_concurrent: 3` bought almost nothing (1.16x) — Ollama itself
   was still the bottleneck, and our lease just let extra requests queue
   inside Ollama instead of inside our own pool. At `NUM_PARALLEL=3`, the same
   `max_concurrent: 3` produced a genuine ~2x speedup. **The pool's
   `max_concurrent` should match the backend's actual configured parallelism,
   not be set independently of it.**
2. **Model identity matters more than request count.** Regardless of
   `NUM_PARALLEL`, switching between different models costs ~4-9s of reload
   time per switch (with `OLLAMA_MAX_LOADED_MODELS=1`), which dominates total
   time far more than concurrency does either way. Running different-model
   requests concurrently doesn't parallelize the reload — it can make it
   worse via contention.
3. **Recommendation for this machine:** keep `OLLAMA_NUM_PARALLEL=3` (applied
   via the systemd override) and `compute_pools: local-ollama: max_concurrent: 3`
   in `~/.config/prisma/config.yaml`, since the two now agree and the
   benchmark confirms real throughput gain — but only for same-model traffic.
   Callers that use different models (Graphify's extraction model vs. the
   analysis agent's model vs. ChromaDB's embedding model) must not be treated
   as fungible against the same pool slot — see below.

## Making the pool model-aware

The numbers above led to a design change in `ResourceManager`
(`prisma/server/supervisor.py`) and `resource_lock` (ADR-012): pools can be
marked `model_affinity` (default: **true**), meaning the pool represents one
hardware unit that can hold exactly one resident model's weights at a time —
one GPU, or one Ollama instance bound to one GPU. On such a pool:

- Concurrent leases are granted freely as long as every requester wants the
  **same** model as whichever one is currently resident (up to
  `max_concurrent`) — this is the Run 2 scenario above, the real ~2x.
- A request for a **different** model than the one currently resident is
  denied outright, the same as "pool full" — the caller's existing
  retry/backoff (`resource_lock.lease()`) naturally waits until every lease
  for the current model releases and the pool goes idle, at which point the
  next request's model becomes the new resident one.
- This is what makes two tasks that each pin to a different model (e.g.
  Graphify's `qwen2.5-graphify:7b` vs. the analysis agent's `qwen2.5:7b`)
  correctly serialize against each other instead of "concurrently" thrashing
  the GPU with alternating reloads — exactly the Run 1/Run 2 mixed-model
  numbers above, which stayed bad (~20s either way) regardless of
  `NUM_PARALLEL`, because that knob only ever affected same-model batching.

**`model_affinity` defaults to true, not false.** The reasoning: this
reload-penalty behavior is a property of real hardware — a single Ollama
instance backed by a GPU (or several GPUs it's still managing as one load
slot) can only hold one model at a time, whether you notice it or not. The
only pools that should override this to `model_affinity: false` are ones
with no such constraint at all: a cloud API that auto-scales and auto-routes
across models with no reload penalty. Getting this backwards — assuming a
hardware-backed pool has no model constraint — is exactly the bug this
change fixes; getting it right requires no config for the common case, since
the default already matches reality.

**Multiple GPUs.** One pool models one hardware unit that holds one resident
model — it does *not* try to model an entire multi-GPU machine as a single
pool with a bigger `max_concurrent`. If a machine has several GPUs and you
want them able to serve different models at once (e.g. one GPU dedicated to
the "intelligent"/large model, another to a smaller fast one), declare one
pool per GPU:

```yaml
compute_pools:
  - name: gpu0_ollama       # dedicated to the large/"intelligent" model
    max_concurrent: 1
  - name: gpu1_ollama       # dedicated to a smaller model, or spare capacity
    max_concurrent: 3
```

`acquire()` already tries every pool when the caller doesn't request one
specifically (`pool=None`), in configured order — so a request for a model
already resident on `gpu1_ollama` lands there if it has room, and a request
for a model resident on neither pool lands on whichever is idle. This also
covers "spread the same model across more GPUs when one isn't enough":
requests for model X fill `gpu0_ollama` up to its `max_concurrent`, then
naturally spill onto `gpu1_ollama` once that's exhausted, loading model X
there too (paying one reload on that second GPU, then batching freely).
No new mechanism was needed for this — it falls out of "every pool is
independent, and the caller just says which model, not which pool."

**Summary of the three shapes this can take:**

| Setup | Config | Behavior |
|---|---|---|
| One local GPU, one Ollama instance | single pool, `model_affinity: true` (default) | same-model calls batch up to `max_concurrent`; different-model calls fully serialize (this doc's benchmark) |
| Local AI server with N GPUs, models pinned per GPU | one pool per GPU, each `model_affinity: true` | different models run genuinely concurrently, each on its own GPU; same-model traffic can also spill across GPUs if declared that way |
| Cloud API | single pool, `model_affinity: false` | any mix of models runs concurrently up to `max_concurrent`, no serialization — the only case where this is actually true |

## Follow-up (2026-07-02): `NUM_PARALLEL` 3 → 4, and a related correction

Two changes since the recommendation above, both driven by real
measurements rather than re-guessing:

**The model consolidation.** `prisma-kg:7b` and `prisma-chat:7b` (two
separate tags, one supposedly at `num_ctx=65536`, the other at `32768`)
turned out to be running at the *same* effective context the whole time —
Qwen2.5-7B's own architecture caps at 32768 tokens, and Ollama silently
clamps a higher configured `num_ctx` rather than erroring. The 65536 claim
in this project's docs (ADR-013, `installation.md`) was wrong — verified
via `ollama show --modelfile`, which only echoes back the *configured*
value, not the actually-enforced one (`/api/ps`'s `context_length` is the
one to trust). Since both tags were functionally identical, they were
merged into one, `prisma-llm:7b`, used for both knowledge graph extraction
and chat.

**`OLLAMA_NUM_PARALLEL` bumped 3 → 4.** With actual GPU utilization
observed at only ~20-40% during single-threaded extraction, there was
clearly more headroom than 3 parallel slots were using. Bumped the systemd
override to `OLLAMA_NUM_PARALLEL=4` and verified live: 4 genuinely
concurrent calls to `prisma-llm:7b` at 32768 ctx completed successfully
using **~7GB VRAM total, ~9GB still free** of 16GB — comfortably safe, and
consistent with this doc's own conclusion #1 above (the pool's
`max_concurrent` must match the backend's actual configured parallelism).
`compute_pools.local-ollama.models` in `~/.config/prisma/config.yaml` was
updated to `max_concurrent: 4` for `prisma-llm:7b` to match. A live-reload
endpoint (`POST /supervisor/resources/reload`, `prisma reload-resources`
CLI command) was added at the same time so tuning this kind of number
doesn't require restarting the whole supervisor and losing in-flight
leases — see ADR-012's follow-up section.

## Follow-up (2026-07-02): the systemd override was removed entirely

The `OLLAMA_NUM_PARALLEL` systemd drop-in
(`/etc/systemd/system/ollama.service.d/override.conf`) has been **deleted**,
not bumped again. Ollama's own default for this setting is `0` ("auto") —
it picks a parallel-slot count per model based on actual free VRAM at load
time, the same mechanism `OLLAMA_MAX_LOADED_MODELS=0` already uses to
auto-manage how many distinct models stay resident (see the top of this
doc's original conclusions — that recommendation, "keep `NUM_PARALLEL`
pinned and match the pool to it," was reasonable for a benchmark run in
isolation, but pinning it statically fights Ollama's own memory-aware
scheduler once real background load — kg extraction concurrency, chat, and
embedding — is competing for the same GPU).

Prisma's own `max_concurrent` in `~/.config/prisma/config.yaml` no longer
represents "match the backend's fixed parallelism" — it's now a generous
ceiling, and `vram_budget_mb` plus `ResourceManager.acquire`'s live
`/api/ps` query (real reported VRAM per resident model, not a static
estimate) are the actual backstop against overcommit. This is a deliberate
trade: less predictable per-call latency in exchange for not artificially
capping concurrency below what the GPU can genuinely absorb.
