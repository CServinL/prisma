# KG retrieval / `/graph/*` / vault-read review checklist

Distilled from ~36 review findings on the Phase-A knowledge-graph capabilities
(`kg_queries.py`, `prisma/server/graph_routes.py`, `source_reader.py`, the chat
grounding tools). The same defect classes recurred repeatedly because fixes
were applied only at the flagged line, not to the class.

**Run this whole list against any change to KG retrieval, `/graph/*` routes,
vault-file reads, or chat grounding tools — and against the change's siblings,
not just the line being touched.**

## 1. `Entity.source_file` is last-writer, not provenance

`KnowledgeGraphService._upsert()` does `MERGE (e:Entity {id}) SET e.source_file = $rel`
— the row is mutable and last-writer-wins. Extraction ids are `{stem}_{entity}`, so
same-stem files in different directories mint the same id and `_upsert` merges them,
overwriting `source_file`.

- For any **citation / provenance**, use the edge's `RelatesTo.source_file` (immutable,
  one per assertion), not either endpoint entity's `source_file`.
- `god_nodes` (`source_files`), `surprising_connections` (`source_file_a/b`),
  `expand_node` (grounding header), `timeline` (per-document) all follow this.
- `search` relevance, the `expand_node` UI neighbour hint, and `OrphanEntity.source_file`
  legitimately use the entity's own `source_file` (best-effort, non-citation).

## 2. chat-tier filter on **both** endpoints

Every `MATCH (a:Entity)-[r:RelatesTo]-(b:Entity)` needs
`WHERE a.trust_tier <> 'chat' AND b.trust_tier <> 'chat'`. Chats are non-citable
(Axiom 5). "An edge's two endpoints share a trust tier" is *not* a safe assumption —
an id collision plus a later re-extraction at a different tier breaks it, leaking a
chat-asserted relationship (and its chat `source_file`) into a citable surface.

Exception: `entities_for_file` is addressed by an exact `source_file` and is diagnostic
(`/admin/kg/*`), so it deliberately returns whatever that file produced.

## 3. Edge direction

`RelatesTo` is a **directed** rel table. `MATCH (a)-[r]-(b)` (undirected) discards the
stored orientation.

- Undirected match → only `count()` / existence-check with it, or render the relation
  **direction-neutrally** (`--`, not `-->`).
- Want direction → use `->` and two directed queries (see `expand_node`).

## 4. The Kùzu connection is shared, serialized, and not thread-safe

There is one `self._conn`. FastAPI runs sync handlers concurrently, and the background
indexer upserts on it too.

- Every live scan holds `self._lock` (same lock the extraction upserts take).
- Expensive non-Cypher I/O (vault file reads) runs **outside** the lock — split the
  query into a locked scan and an unlocked build (`timeline_scan` / `timeline_build`).
- A derived cache is **computed and published under one lock hold** — a gap lets
  `drop_index()` clear the graph in between and the stale result gets republished.
- The cache refresh must gate on **every** graph mutation: extraction, deletion, and
  rename-relabel (not just `extracted`).
- Every request-path query takes a validated `limit`; free-text query params
  (`?id=`, `?q=`, `?query=`) take a `max_length`.
- Heavy 2-hop enumeration (`surprising_connections`) is background-computed and served
  from cache, never run on a request thread.

Known / deferred: `god_nodes` / `authors` / `vault_health` still do full unbounded
Cypher scans on the live request path under the lock (aggregate-in-Python).

## 5. Grounding-tool contract

A tool marked `grounding=True` (`ToolSpec`) must, for anything it returns:

- carry a **resolvable citable slug** — the compound `dir--name` form via
  `VaultService.slug_for_relpath()`, **never** `Path(x).stem` (which drops the
  directory and collapses duplicate filenames) — rendered in a `Sources:` header, or
  wrap the payload under a real slug (`read_source`, `zotero_search`);
- return **empty text** when it has nothing citable, so
  `ChatAgent._turn_had_no_grounding()` (which keys on `result.text or None`) correctly
  forces the ai-inference wrapper.

## 6. "Bounded slice" means all three

- bounded **input** read — `f.read(N)`, not `path.read_text()[:N]` (don't pull a large
  imported PDF→MD fully into memory);
- bounded **output** size — a cap on total joined chars, not just a match/row count;
- the **`truncated` flag** set on *every* path that shortened the result (per-line
  clip, total-size budget, more matches than shown).

`read_source`'s literal mode is literal-only — no regex engine on caller-controlled
input (`re` has no execution timeout; `(a+)+$` is a catastrophic-backtracking DoS).

## 7. Slug decode safety

`_resolve_compound_slug()` / `_find_md()` decode `dir--name` → a path. Any new caller
(`READ_SOURCE`, `GET /notes/{slug}/read`, `frontmatter_for_relpath`) inherits its
input contract — audit it, don't assume "existing code = safe":

- containment check: `resolved.is_relative_to(self.root.resolve())`;
- `candidate.is_file()`, not `.exists()` (a directory literally named `foo.md`);
- append the known suffix, don't `Path.with_suffix()` (a dotted stem `paper.v1` would
  lose `.v1`);
- catch `ValueError` for degenerate inputs (`"--"` → `/`, leading-separator absolutes).

Open limitation: the `--` separator is unescaped, so a path component containing `--`
does not round-trip; `{stem}_{entity}` ids are not directory-unique. Full fix is an
escape scheme + `{relpath}_{entity}` ids + a reindex — see `TODO.md`.

## 8. Two literals that must agree → one shared constant

e.g. `SURPRISING_CONNECTIONS_MAX` backs both the route's `Query(..., le=...)` and the
background cache's populate size; `TIMELINE_MAX` / `EXPAND_MAX` likewise.

## 9. Tests build state through the real write path

Construct the graph with `_upsert` / real extraction / the public service method —
never hand-assemble the end state (`kg._top_entities_cache = []`, reusing one entity
id across documents, manually assigning `old_topic` / `new_topic` that
`{stem}_{entity}` extraction would never produce). A fixture that dodges the
production invariant proves nothing. And always confirm the test fails on the pre-fix
code (`git stash` the source, run the test, see red).
