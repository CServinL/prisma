# TODO

Open work only. Resolved/historical entries live in git history (and, where the
methodology or findings are independently worth citing, `docs/logs/`) — this file
is a backlog, not a log.

## Chat

- **`/chat` is single-shot, not streaming.** `POST /chat` returns the whole reply
  once the tool loop finishes — no WebSocket/SSE streaming, even though the
  transport already exists for other purposes (ADR-010). Low priority; revisit
  once real response latency (multi-tool-call turns especially) makes it feel
  worthwhile.
- **No output-truncation handling.** Nothing detects/retries a model response
  that got cut off mid-answer (mirroring the old `finish_reason=length` case).
  `semchunk` only bounds *input* size.
- **Optional local ML injection classifier, off by default.** Baseline defense
  (`injection_defense.py`'s mechanical `<untrusted_source>` wrapping) is built
  and mandatory; a small standalone INT8 ONNX classifier
  (`hlyn/prompt-injection-judge-deberta-70m` or
  `protectai/deberta-v3-small-prompt-injection-v2`, ~83MB, CPU-only, no
  framework) would add semantic detection on tool-result content specifically —
  not user input, and not needed until real ingested-content volume justifies
  the extra cost.
- **Consultation sub-agent for large sources** — `get_full_text`'s bounded
  excerpt (`read_source`) is built; a deeper redesign was proposed instead of
  extending it further: a dedicated sub-agent that map-reduces over one
  source's sections (reusing `semchunk`, same pattern
  `KnowledgeGraphService._extract_file` uses), possibly with its own tool loop
  (`expand_node`, graph queries, its own semantic search) to follow threads
  across the graph while consulting a source. Meaningful overlap with existing
  KG extraction to resolve first. Not scoped — needs its own design pass.
- **Cross-chat entity linking** — deferred to its own session (see Phase B of
  the KG-tools plan). Existing cross-chat `RECALL` already does topical-
  similarity search across chats; a real entity-linking feature needs either
  extending KG extraction to chat content (reversing the deliberate "chats are
  not sources" decision) or a new, chat-scoped entity concept. Real
  architectural decision needed before any implementation plan is worth
  writing.
- **Horizontal node-graph view of a chat session** — an alternative to the
  vertical chat view: the main line as a left-to-right timeline, every node
  (tool call, reasoning step, claim, regeneration alternate) rendered as its
  own connected node instead of a collapsed sub-panel, to make it easier to
  see how `RECALL` hits and regeneration alternates get referenced back into
  the main line. `session_graph.py`'s `build_session_graph()` already has
  every node/edge type this would need — this would be a new renderer, not a
  new backend representation. Not scoped or designed (open question: toggle
  on the same chat, or a separate page?).

## Knowledge graph

- **`ranked_nodes`/`query`'s full neighbor-expansion-with-proximity-weighting
  sophistication is deferred** — `search()` (what both wrap) is still a flat
  term-match scan, not the richer graph-proximity ranking from the original
  design. Deliberate, not an oversight (see ADR-013).
- **Image extraction gap** — the KG module's file scan is `.md`-only;
  vision-model extraction for `.png`/`.jpg`/`.jpeg`/`.webp`/`.gif` (present in
  the old Graphify-era config) was never carried over.
- **KG entity ids aren't directory-unique** — extraction mints ids as
  `{stem}_{entity}`, so same-stem files in different directories collide and
  `_upsert()`'s `MERGE (e:Entity {id})` silently collapses them into one row
  (last-writer-wins `source_file`/`trust_tier`). Same root cause as the
  compound-slug issue below. Real fix: `{relpath}_{entity}` ids + a full graph
  rebuild.
  - One consequence of the collision worth naming: an entity's `trust_tier`
    can end up out of sync with an edge asserted alongside it, so a
    chat-tier-drifted edge could in principle be cited as if it were a real
    document. Currently inert — chats are never indexed into the graph at all
    (`.sess`, not `.md`/`.txt`) — and "chats aren't sources" doesn't actually
    depend on this filter anyway (chats' storage format + `ChromaIndexer`'s
    explicit exclusion + `RECALL` being the one non-citable path already
    guarantee it independently). Worth closing alongside the id fix above,
    not urgent on its own.
- **Compound-slug `--` separator is not collision-safe** —
  `VaultService.slug_for_relpath()`'s `dir--name` encoding isn't an inverse of
  its own decode whenever a path component contains `--`
  (`archive/foo--bar.md` → `archive--foo--bar` → decodes back to
  `archive/foo/bar.md`, a different path). A correct fix is an escape scheme
  applied consistently across every consumer (`VaultRef.parse`/`.compound_slug`,
  `vault.py`'s decode path, `renderer.py`'s wiki-link resolution, the UI's
  "Copy slug" action) plus a migration path for already-persisted compound
  slugs. Its own design pass, not a quick fix.
- **Evaluate Crawl4AI** for research-stream discovery beyond
  arxiv/semanticscholar's structured APIs — could extend `stream_runner.py`'s
  discovery to journal/preprint/lab pages without a clean API. Not evaluated —
  a product-scope decision (does this want raw web ingestion at all), not just
  a code-fit one.
- **Assess DSPy** for prompt optimization — not surveyed at all yet. Worth a
  look if prompt-optimization becomes a priority for structured-extraction
  prompts.

## Infra

- **`pending_queue.py`'s default queue file path is CWD-relative**
  (`./data/pending_writes.json`), not anchored to an explicit data directory —
  works by accident under a working directory that happens to be on
  persistent storage, silently stops persisting across a restart otherwise.
  Needs an explicit fix (env override, absolute path under a configured data
  dir).
- **Vault unlock over LAN instead of an at-rest key** — design sketch exists
  (gocryptfs mount gated behind a local-network-only unlock endpoint, vault-
  dependent features unavailable until unlocked) but several pieces are
  undesigned: where the "locked" state actually gates each subsystem, auth on
  the unlock endpoint itself, and clean re-entry into the locked state on
  process restart (needs the supervisor's crash-recoverable model, ADR-012).
- **Package the desktop client as a Flatpak** — not started. Two approaches
  undecided: a pragmatic unsandboxed build (fast, not Flathub-submittable) vs.
  a Flathub-correct sandboxed build (needs vendoring every crate's sources
  offline first via `flatpak-cargo-generator`).
