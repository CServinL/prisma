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
- **Optional local ML injection classifier, off by default — low priority.**
  Baseline defense (`injection_defense.py`'s mechanical `<untrusted_source>`
  wrapping) is built and mandatory; a small standalone INT8 ONNX classifier
  (`hlyn/prompt-injection-judge-deberta-70m` or
  `protectai/deberta-v3-small-prompt-injection-v2`, ~83MB, CPU-only, no
  framework) would add semantic detection on tool-result content specifically —
  not user input, and not needed until real ingested-content volume justifies
  the extra cost. Lower urgency than the wording alone suggests: every chat
  tool (`search_vault`, `graph_context`, `expand_node`, `god_nodes`,
  `surprising_connections`, `suggest_questions`, `read_source`, `recall`,
  `think`, `zotero_search`) is read-only — nothing writes, deletes, or
  reaches outside the vault/Zotero read — so there's no capability for an
  injected instruction to hijack. The residual risk this would catch is
  narrower: a poisoned document making the model state a false claim with a
  confident `qualifier`/fabricated `warrant` rather than the model *doing*
  something.
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

## Vault

- **File upload routes buffer the whole body into memory before any
  validation runs.** Both `upload_source_companion()` (`notes_routes.py`,
  `data = file.file.read()` — a plain `def` reading the underlying
  `SpooledTemporaryFile` synchronously, not `await file.read()`; this
  route deliberately isn't `async def`, so it can run in FastAPI's
  threadpool instead of blocking the shared event loop for its own
  multi-second PDF/HTML extraction — don't reintroduce `await file.read()`
  here when picking this up) and the pre-existing `upload_chat_attachment()`
  (`app.py`, genuinely `async def`+`await file.read()`, since that route
  does no CPU-bound extraction) read the entire `UploadFile` before
  checking extension or size, so an oversized upload can pressure/OOM the
  process before the existing extension allowlist ever gets a chance to
  reject it. Systemic — no upload route in this codebase has a size cap or
  streams-then-validates — not something to bolt onto just the new
  companion route in isolation.
- **Form-dialog error messages can render a raw FastAPI validation-error
  array instead of text.** `sourceFormError = err.detail ?? ...`
  (`+page.svelte`) assumes `detail` is always a string, but a Pydantic 422
  (e.g. a bad `year`) returns `detail` as a list of validator-error objects,
  which renders unreadably. Pre-existing pattern, not introduced by the
  Source dialog — `streamFormError` does the identical `err.detail ?? ...`
  a few hundred lines up for the same reason. Needs a shared "stringify a
  FastAPI error detail" helper used by both, not a Source-only fix.
- **Vault file writes have no per-file locking, anywhere, except Source.**
  `save_note()` is still a plain read-parse-write of a whole `.md` file
  with no lock — two requests touching the *same* note close together (two
  browser tabs, a double-click) can each read stale frontmatter and one
  write silently clobbers the other's change, no error to either caller.
  Pre-existing, systemic, not Source-specific: `_chat_write_lock`/
  `_path_write_lock` show the established one-lock-per-concern pattern for
  exactly this class of race, but nothing plays that role for Note/Stream.
  A real fix needs a per-slug (or global) write lock applied consistently
  across every vault-file-mutating method, not a lock added piecemeal to
  whichever route happens to get touched next — its own design pass.
  `update_source_bibliographic_fields()`/`attach_source_companion()`/
  `ensure_md_format()`/`set_node_type()` are now the exception: all four
  hold `_source_write_lock` end-to-end (closing the same-slug
  edit-vs-upload-vs-type-change-vs-md-generation lost-update race), but
  that lock is global, not per-slug — a companion upload's multi-second
  PDF/HTML extraction now also blocks metadata edits, type changes, *and*
  creates for every unrelated source for that whole duration, a real
  cross-slug contention cost traded for correctness rather than a free
  fix. Worth revisiting as part of the same design pass above (a per-slug
  lock would remove this cost entirely) rather than accepted as permanent.
  Two more pre-existing, untouched-by-this-diff call paths write a
  Source's `.md` file completely outside this locking, found auditing
  every writer of that file but deliberately not folded into the four
  above — each needs more than "just add a lock", not a mechanical fit
  for this pass:
  - `rename_node()` (`POST /nodes/{slug}/rename`) has the same unlocked
    race *and* a second, independent bug: its companion-rename logic only
    triggers for a `.html`-suffixed primary file, never for a Source
    (always `.md`). Renaming a Source leaves its `.pdf`/`.html` companion
    on disk under the *old* slug — `find_companion()` can no longer find
    it under the new one, permanently orphaning it, and a subsequent
    companion upload silently duplicates storage instead of replacing it.
    Fixing this needs actual companion-rename logic added, not just a
    lock.
  - `write_by_path()` (`/sync/file`, the desktop-sync write path) uses a
    *different* lock (`_path_write_lock`) that was never made to exclude
    `_source_write_lock` — a synced desktop edit landing on a Source's
    `.md` file at the same moment as a locked API-side edit can still
    race, just via two uncoordinated locks instead of no lock at all.
    Needs an actual cross-lock design decision (one lock covering both
    paths, or an explicit lock-ordering rule), not a mechanical fit either.
- **No UI to view a companion file** — `COMPANION_EXTS` covers pdf/html/htm/
  svg/epub/docx/tex/drawio/jpg/jpeg, and the backend already serves any of
  them generically (`GET /notes/{slug}/original`, `FileResponse`), but the
  UI only ever does anything with `.html` companions (the existing
  `format-toggle`/`Open HTML` buttons and `<iframe class="html-frame">` in
  `+page.svelte`, backed by the html-specific `GET /notes/{slug}/view`).
  Every other companion type is currently invisible in the UI — a source
  with a PDF/SVG/EPUB/DOCX/TeX/drawio/JPG companion only ever shows its
  derived `.md` text, with no way to see the original at all. Needs
  generalizing the existing html-only toggle into a per-companion-type "view
  original" affordance (a tab, in the existing toolbar location).
  Per-format choice is driven by DOM-pollution risk, not by "can a browser
  render this," and not by trust/origin (our own first-party generated HTML,
  e.g. `docs/diagrams/*.html`, is exactly as DOM-polluting as an imported
  one if ever shown inline — the format is what matters, not who made it):
  - **html** — `<iframe>`, as today. This is the one format that must always
    be isolated.
  - **pdf** — `<iframe>`/`<embed>` pointed at `/original` is fine as-is: the
    browser's native PDF viewer already runs in its own sandboxed context,
    not against our page's DOM.
  - **svg** — safe via `<img src=".../original">` (browsers never execute a
    `<script>`/event handler embedded in an `<img>`-sourced SVG). Must
    *never* be inlined into the DOM directly (e.g. a Svelte `{@html}` of the
    raw markup) — that would need the same iframe treatment as html.
  - **jpg/jpeg** (and any future png/gif/webp, see the image-extraction-gap
    item above) — plain `<img>`, no isolation concern, it's raster data.
  - **docx/epub/drawio/tex** — no reasonable inline browser renderer either
    way; download-link fallback, not an embed decision.
  Separately, a real gap in the *existing* html iframe: `<iframe
  class="html-frame">` sets no `sandbox` attribute today, so the isolation
  it's supposed to provide is only partial (a bare `<iframe src>` does put
  the content in its own document, but without `sandbox` it still gets full
  script execution, top-level navigation, form submission, etc.). Worth
  fixing regardless of the broader per-format work — needs
  `sandbox="allow-scripts"` at minimum to keep the existing `postMessage`
  external-link-click interceptor working, tightened further if nothing
  else in that script needs more than that. Deliberately **not**
  `allow-same-origin` alongside `allow-scripts` — that combo is a known
  sandbox-escape antipattern when the framed document shares an origin with
  the embedding app (a real possibility here, API and web app both being
  localhost), since it lets the framed script reach back into the parent
  page's own DOM, defeating the isolation entirely. The consequence: without
  `allow-same-origin` the framed document's origin is opaque (`Origin:
  null`), and `app.py`'s CORS middleware (`allow_origin_regex=
  r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"`) correctly does *not* match
  `null` — so any script inside an arbitrary imported HTML companion that
  tries a same-origin-relative `fetch()`/XHR back to the API will be
  silently blocked. That's the right default (fail closed on arbitrary
  imported content, not fail open), not a bug to "fix" by special-casing
  `null` in the CORS allow-list later — a `null`-origin CORS allowance isn't
  scoped to *this* iframe, it would apply to any sandboxed frame from
  anywhere. Our own self-contained content (e.g. the `docs/diagrams/*.html`
  atlas) doesn't hit this at all — checked, none of them do a live `fetch()`,
  data is embedded inline — so this only matters for arbitrary imported HTML
  companions, and only if one ever legitimately needs to call back to the
  API from inside the frame (none currently do).
  Not scoped in detail — needs its own small design pass on the toolbar/tab
  UI, not just wiring up `/original`.

## Knowledge graph

- **`ranked_nodes`/`query`'s full neighbor-expansion-with-proximity-weighting
  sophistication is deferred** — `search()` (what both wrap) is still a flat
  term-match scan, not the richer graph-proximity ranking from the original
  design. Deliberate, not an oversight (see ADR-013).
- **Image extraction gap** — the KG module's file scan is `.md`-only;
  vision-model extraction for `.png`/`.jpg`/`.jpeg`/`.webp`/`.gif` was never
  carried over. Two separate pieces:
  (1) `docu-craft` has no image→markdown path at all yet — that's the actual
  extraction work, and belongs in `docu-craft` itself, not here, since
  `VaultService.ensure_md_format()` already delegates any non-PDF companion
  to a generic `docu_craft.render(format="md")` call; once docu-craft can
  handle images, this side likely needs no new extraction code, just wiring.
  (2) On this side: `jpg`/`jpeg` are already recognized (`COMPANION_EXTS`,
  `MediaKind.jpg`) but produce no text today (the generic docu-craft render
  call fails quietly on a bare image); `png`/`webp`/`gif` aren't recognized
  as companions or `MediaKind` at all — they only appear in `app.py`'s
  unrelated static-asset allowlist (`_ALLOWED_ASSET_EXTS`, shared with
  `.css`/`.js`/fonts). Both are attachments, never first-class vault/KG
  nodes, by design — extraction would only ever populate a caption/text
  handle in the sibling `.md`, same role PDF extraction already plays.
- **KG entity ids aren't directory-unique** — the extraction system prompt
  (not Python code) tells the model to mint ids as `{stem}_{entity}`, so
  same-stem files in different directories collide and `_upsert()`'s
  `MERGE (e:Entity {id})` silently collapses them into one row
  (last-writer-wins `source_file`/`trust_tier`/`label`). Same root cause as
  the compound-slug issue below. No LLM re-run needed either to fix this or
  to migrate existing data — `_upsert(rel, ...)` already has `rel` in scope,
  so ids should be minted in Python from `rel` + the extracted label,
  ignoring whatever id string the model self-reports (needs the same
  `/`-escaping care as the compound-slug fix below). For existing data: `id`
  is a Kùzu primary key (can't be renamed via `SET`, needs node
  replace-and-repoint), but `RelatesTo.source_file` was never clobbered by
  the collision — it's stamped per edge, so the distinct `source_file`s
  among an entity's edges tell you exactly how many real files are
  coalesced into it. A pure Cypher/Python migration can replace each
  colliding node with one new node per distinct `source_file`, re-pointing
  each edge to the split node matching its own `source_file` — no LLM call.
  The one gap: whichever file's attributes lost the original last-write race
  (label casing, author/source_location specifics) can't be perfectly
  recovered by this migration — split copies inherit the currently-surviving
  merged values as an approximation. Acceptable; not a reason to re-extract.
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

- **PyPI distribution name `prisma` is already taken** — by the unrelated
  Prisma ORM's Python client ("Prisma Client Python"). `pyproject.toml` still
  declares `name = "prisma"`; the project was never actually published (docs
  said "install from PyPI" but that never happened). `pip install prisma`
  installs the wrong package. Needs a distribution-name decision (the
  `prisma` console script/CLI name can likely stay as-is even under a
  different PyPI project name) before ever publishing.
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
- **Desktop app is single-window** — `tauri.conf.json`'s `app.windows` array
  declares exactly one window, and the whole UI's state is one global
  `activeNode` in `+page.svelte` — no way to have two nodes (a source and
  the chat discussing it, say) open side by side today, in either the
  desktop shell or the browser/PWA. Preferred direction, modeled on Zen
  Browser: a vertical/sidebar tab list (not a horizontal top bar — maximizes
  vertical work area, which matters more here than horizontal for reading
  long note/source/chat content, and fits naturally alongside the existing
  resizable/collapsible left `.sidebar` rather than adding a second,
  competing UI convention), where each tab is a genuinely independent app
  instance — its own state, own WebSocket connection, not just a shared
  `activeNode` swapped in place — plus Zen's side-by-side split view so two
  tabs can be viewed at once. Several concrete pairings want exactly this:
  a chat next to the source(s) it's grounded in, a node next to its
  companion (see the companion-viewer item above), a note next to a
  linked-item it references.
  Two different mechanisms could deliver "independent," not decided between:
  (1) Tauri v2 supports multiple independent webviews within a single
  window (verify current API surface when scoping) — each sidebar tab backed
  by its own real webview, positioned/sized to fill the content area or
  split it in two; desktop-only, no equivalent in the browser/PWA. (2) An
  `<iframe>` per tab, each loading `/app` fresh — a genuinely separate
  browsing context/JS realm even in a plain browser, so the same mechanism
  works identically in the desktop shell, browser, and PWA, at the cost of
  N full app reloads instead of native multi-webview efficiency. Not
  scoped — needs a decision between the two before either is worth
  designing further.
- **Browser/PWA has no local vault sync** — only the Tauri build
  (`prisma-desktop/src-tauri/src/sync/`) has a local vault-sync engine
  (fs-watcher push, WS pull, offline-first reconciliation); the browser/PWA
  path has no persistent local filesystem at all, so it always talks live to
  the API with no offline copy. Deliberate, not an oversight (Tauri is the
  primary/official app for now, per 2026-07-25 decision) — but a real,
  unstarted gap, not just a lower-priority version of the same feature.
  Would need the File System Access API (Chromium-only, no Firefox/Safari/
  iOS, no native fs-watch, weaker permission persistence) — a genuinely
  different implementation from `prisma-desktop`'s Rust engine, not a port
  of it. Not scoped — its own future session, not a quick follow-up.
