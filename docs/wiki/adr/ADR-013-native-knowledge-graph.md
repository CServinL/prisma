# ADR-013: Native Knowledge Graph — Replacing Graphify with Kùzu

**Date:** 2026-07-01
**Author:** CServinL
**Status:** Accepted

## Context

The knowledge-graph layer of the hybrid retrieval design (ADR-009) was built
on `graphify`, a third-party pip dependency: it extracted entities/relations
via an LLM and persisted them to a flat `graphify-out/graph.json`, loaded
into `networkx` in memory for traversal. Two real problems surfaced from
using it, not a preference for owning more code:

1. **No incremental upsert.** `graph.json` is a single flat blob. Every
   query reparsed the whole file into `networkx` in memory; there was no way
   to update just the nodes/edges for one changed file without touching the
   rest of the graph's storage representation.
2. **Per-file chunking with no recovery path.** Graphify chunked by
   *file*, not by section. A single document too large for the model's
   token budget had no fallback — it silently returned a truncated,
   incomplete extraction on every run, forever, with no way to recover short
   of manually splitting the source file. This was confirmed live in this
   vault with a real paper (`Cunningham_2023_SAEs_Interpretable_Features.md`)
   that never fully indexed under Graphify. See `docs/ollama-concurrency.md`
   and `TODO.md` for the investigation.

Both problems are structural to Graphify's design, not bugs fixable within
it. Separately, ADR-012's process-supervision work established that Graphify
ran as an on-demand subprocess spawned by the API process — workable, but it
meant a wedged or crashed extraction run could still affect the API
process's own subprocess-management code path, and gave the supervisor no
first-class visibility into it (see ADR-012's compute-pool-leasing addendum,
which was itself triggered by a Graphify concurrency incident).

## Decision

Replace `graphify` with a native module, `KnowledgeGraphService`
(`prisma/services/knowledge_graph_service.py`), storing the graph in an
embedded **Kùzu** database instead of flat JSON, and chunking extraction
**per section** (heading/token-budget-aware, via `semchunk`) instead of
per file.

### Storage: Kùzu, not Neo4j, not a flat file

Three options were weighed for what should replace `graph.json` +
`networkx`:

- **Keep `networkx` + JSON, just fix the incremental-upsert gap in-house.**
  Rejected — doesn't address the deeper issue that an in-memory graph
  library with a JSON-file backing store has no real query language, no
  indexing, and no answer for "large graph doesn't fit comfortably in
  memory" as the vault grows. Patching around it would mean slowly
  reinventing a graph database, badly.
- **Neo4j.** Rejected as too heavy for this vault's actual scale (hundreds
  of documents, not millions of nodes) — it requires a JVM and a standalone
  server process, which is precisely the kind of extra long-running
  component ADR-012 was working to minimize, not add.
- **Kùzu (chosen).** Embedded — no server process, no JVM — with real
  Cypher-like traversal and native support for property graphs. Matches the
  vault's actual scale, and keeps the "no extra service to run" property
  that made `chroma run` the exception (ChromaDB needed its own server
  precisely to get crash isolation ADR-012 wanted; Kùzu doesn't need a
  server to get a real query language).

Kùzu's concurrency model was verified empirically before committing to it:
only **one process** may ever hold a Kùzu database open — a `READ_WRITE`
connection locks out every other `Database` object, even `READ_ONLY` ones,
in any other process (`RuntimeError: Could not set lock on file`). Not a
blocker, since only one process needs graph access at all, but it directly
shaped where `KnowledgeGraphService` could live (see below).

### Extraction: per-section, not per-file

`semchunk.chunkerify(...)` splits each document by a token budget
(`token_budget`, currently 8000 — see the service's constructor) before any
LLM call is made, and each section's nodes/edges are upserted
independently. A single oversized document now degrades gracefully into
multiple sections instead of silently truncating forever. Each section's
extraction call reports its own success/failure (`_call_ollama_extract`
returns `(nodes, edges, ok)`); the file's manifest hash — which gates
whether it's re-processed on the next pass — only advances if *every*
section succeeded, so a file that changed while Ollama was unreachable is
correctly retried rather than marked done. (This distinction was a real bug
caught during this work — see `docs/wiki/roadmap.md`'s Ollama-resilience
item.)

### Runs as its own supervised worker process, not embedded in `api`

Kùzu's single-process-only constraint, combined with the same
crash-isolation reasoning ADR-012 already applied to ChromaDB, means
`KnowledgeGraphService` runs as a 4th supervised worker
(`prisma/server/kg_app.py`, a small FastAPI app, port `:8768` by default) —
not embedded inside the `api` process, and not an on-demand subprocess like
Graphify was. A native-extension crash or a wedged extraction call no
longer risks the REST/WebSocket process, the supervisor can restart it
independently, and its CPU-bound work (section chunking, Cypher upserts)
runs on its own core instead of competing with `api`'s event loop. Unlike
ChromaDB, there's no ready-made server binary for Kùzu (`chroma run`
already existed; `kuzu serve` doesn't) — `kg_app.py` *is* that server,
purpose-built.

`app.py` talks to it over HTTP through `KnowledgeGraphClient`
(`prisma/services/knowledge_graph_client.py`), a thin client matching
`KnowledgeGraphService`'s exact method names, so no call-site changes were
needed beyond construction. It does client-side score-merging for
`ollama_deep_search()` since ChromaDB and the knowledge graph now live in
different processes. Resource-lock holder is `"kg"` (matching the worker
name), same `local-ollama` compute pool and `model_affinity` behavior as
before (ADR-012), just correctly attributed for `release_all_held_by()` to
fire on crash/restart. Gets its own log file (`kg.log`,
`/logs?concern=kg`), same pattern as `chroma`/`ollama`/`activity`/`maintenance`.

### Extraction model: `prisma-kg:7b`

The Ollama model used for extraction was renamed from `qwen2.5-graphify:7b`
to `prisma-kg:7b` (`ollama cp` + `ollama rm`, no re-download — same
underlying weights) to drop the vestigial "graphify" name now that the
dependency it referenced is gone. Its context window was also increased
from the baked-in 16384 to 65536 tokens (`num_ctx` in the Modelfile),
verified empirically to fit comfortably in available VRAM at the real
`OLLAMA_NUM_PARALLEL=3` concurrency this deployment runs at (~9GB used of
16GB total, vs. a naive linear KV-cache estimate that overpredicted cost —
Qwen2.5's GQA architecture makes the real cost much lower per additional
context token). `KnowledgeGraphService`'s `token_budget` default was raised
from 1500 to 8000 to actually make use of that headroom — most vault
documents now extract in a single section instead of several — while still
leaving generous room under 65536 for the system prompt, the
`<untrusted_source>` injection-defense wrapping, and the model's own JSON
output.

#### Follow-up (2026-07-02): the 65536 claim was wrong, and the models were merged

The "increased to 65536 tokens, verified empirically" claim above is
**incorrect** — worth leaving visible rather than silently edited, since
the mistake and how it was found are useful on their own. `ollama show
--modelfile` only echoes back the `num_ctx` value that was *configured*,
not what's actually *enforced*. Qwen2.5-7B's own architecture caps at
32768 tokens of context; Ollama silently clamps any higher configured
`num_ctx` down to that ceiling rather than erroring or warning. The "~9GB
VRAM" measurement above was real, but it was measuring the model running
at the true clamped 32768, not 65536 — the verification checked the wrong
thing (the Modelfile's own echo) instead of `/api/ps`'s actually-loaded
`context_length`.

Once this surfaced, it also meant `prisma-kg:7b` and `prisma-chat:7b`
(ADR-014) — two separate tags, believed to need different `num_ctx` values
— had been running at the *same* real context the entire time. Since they
were functionally identical, they were merged into one tag, `prisma-llm:7b`,
used for both extraction and chat. `KnowledgeGraphService`'s
`ollama_model` default and `ChatConfig.model`'s default both point at it
now. `token_budget=8000` (per-section chunk size) is unaffected by this
correction — it was always comfortably under even the true 32768 ceiling,
so extraction correctness was never actually at risk, only the documented
context-window number was wrong. See `docs/ollama-concurrency.md`'s own
follow-up section for the full story, including a related
`OLLAMA_NUM_PARALLEL` 3→4 bump discovered around the same time.

## Alternatives Considered

See "Storage" above for the graph-backend alternatives (keep
`networkx`+JSON, Neo4j). The only other alternative considered for the
*process* question was keeping `KnowledgeGraphService` embedded inside the
`api` process (as Graphify effectively was, being spawned by it) — rejected
for the crash-isolation and supervisor-visibility reasons above, and
because Kùzu's single-process constraint makes an in-`api` connection a
liability the moment any other code path (a future CLI inspection command,
a test fixture) tries to open the same database file concurrently.

## Consequences

### Positive
- No more silent, unrecoverable truncation for oversized documents —
  per-section chunking degrades gracefully instead.
- Incremental upsert is now real: Cypher `MERGE`-style upserts per section,
  not a full-file JSON rewrite.
- A knowledge-graph extraction crash or hang no longer risks the API
  process; the supervisor has first-class visibility and independent
  restart control over it, same as `chroma`.
- One fewer third-party pip dependency (`graphifyy` removed from
  `pyproject.toml`).
- Retrieval call sites (`ranked_nodes`, `query`) are drop-in compatible —
  ADR-009's hybrid-scoring design required no changes.

### Negative
- A 4th long-running worker process — more moving parts for the supervisor
  to manage, one more port (`:8768`).
- Kùzu's single-process-only constraint means no external tool or script
  can inspect the graph database file directly (even read-only) while
  `kg_app.py` is running — any future debugging/inspection tooling has to
  go through the `kg` process's own HTTP API.
- `ranked_nodes`/`query`'s full neighbor-expansion-with-proximity-weighting
  sophistication from the original design is deliberately deferred (a
  simpler term-match-only `search()` for now) — tracked in `TODO.md`, not
  an oversight.

## Related ADRs

- ADR-009: Hybrid Retrieval Architecture (the retrieval design this module
  plugs into unchanged; its own follow-up section links back here)
- ADR-012: Process Supervision (the supervised-worker pattern, compute-pool
  leasing, and crash-isolation reasoning this decision extends to a 4th
  worker)
