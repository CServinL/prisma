# ADR-019: Persisted Format Governance & Migrations

**Date:** 2026-08-04
**Author:** CServinL
**Status:** Proposed — narrow version (chat `prisma:meta` blob, and its
successor the `.sess` format) implemented as a concrete first instance,
Python-only by design (see open question 2: chat sessions never touch
Rust). Open questions 1/3 (extending versioning to vault frontmatter
generally, and where migration logic should live for that broader case)
still need cservinl's decision.

## Context

[ADR-017's 2026-08-04 persistence fix](ADR-017-claim-attribution-and-footnote-model.md#persistence--ui-interactivity-fixes-added-2026-08-04)
added a `<!-- prisma:meta {...} -->` JSON blob to the chat `.md` format,
carrying `model`/`footnotes` per turn. Writing it surfaced a gap: **nothing
in this codebase tracks what shape a persisted file's data is in.** Every
format change so far has been handled ad hoc, three different ways:

- **Per-field Pydantic defaults** (`Field(default_factory=...)`,
  `#[serde(default = "fn")]` on the prisma-desktop/Rust side) — works for
  *adding* an optional field, silently wrong for a *rename* or a field whose
  *meaning* changes (a default can't know "this old value meant something
  different").
- **Defensive parsing** (`_parse_chat_body`'s meta-comment handling, this
  same session: malformed JSON degrades to "no metadata," never breaks
  loading the rest of the chat) — good for surviving corruption, says
  nothing about *which* shape a file is actually in, so it can't
  distinguish "old format, needs upgrading" from "genuinely malformed."
- **Dual-format acceptance** (`_parse_frontmatter` still accepts a legacy
  HTML-comment style alongside YAML, per its own docstring) — works, but
  each instance is a bespoke one-off with no shared pattern, and the
  original format's acceptance code has no expiry — it stays forever
  because nothing marks it as "old."

None of these answer "what schema version is this file on" or give a
single, testable place to put an upgrade step when the format changes
again. cservinl asked for real governance over this — a versioned format
plus explicit migrations, done through Pydantic where it fits rather than
ad hoc per call site.

## Decision (narrow instance, built 2026-08-04)

The `prisma:meta` JSON blob now carries its own `schema_version`, checked
and upgraded through a single dispatch function before its contents are
used:

```python
CHAT_META_SCHEMA_VERSION = 1

def _migrate_chat_meta(raw: dict) -> dict:
    version = raw.get("schema_version", 1)  # absent = written before this
                                              # existed (2026-08-04 same-day
                                              # code), already shape v1
    if version > CHAT_META_SCHEMA_VERSION:
        raise ValueError(
            f"prisma:meta schema_version {version} is newer than this "
            f"build supports ({CHAT_META_SCHEMA_VERSION})"
        )
    # No migrations yet -- next format change adds a step here:
    #   if version == 1:
    #       raw = {...upgraded...}
    #       version = 2
    # Never rewrite an existing step once shipped -- each version's
    # upgrade path must stay independently correct for a file frozen at
    # that version, however old.
    return raw
```

Composes with the existing defensive-parsing contract for free: `_parse_chat_body`
already catches `ValueError` around the meta-comment JSON decode and
degrades to "no metadata for this turn" rather than breaking chat load —
`_migrate_chat_meta` raising for an unrecognized future version (an older
binary reading a file a newer one wrote) falls into that same path, no new
exception handling needed.

`schema_version` is written unconditionally by `_render_chat_body` going
forward, so every *new* write is self-describing from here on, even before
there's ever a version 2 to migrate from.

## Should chat sessions even be `.md`? (raised 2026-08-04)

cservinl's framing: of everything a Chat persists, only the **Excerpt**
(the distilled Summary note, ADR-015) is genuinely prose — the rest
(`tool_calls`, `footnotes`, `model`) is structured, typed data that just
happens to be *embedded inside* a `.md` file, via increasingly elaborate
conventions layered on top of plain markdown (`> used \`tool\`: query`
blockquote lines, and now this ADR's `<!-- prisma:meta {...} -->` JSON-in-
HTML-comment). Each of those is markdown *abused* to carry non-markdown
data, not markdown used for what it's actually good at. `.md` earns its
keep for Notes/Sources/the Excerpt — genuinely-prose content a plain
markdown viewer should render meaningfully — but a chat session's
structured metadata was never really prose to begin with.

This reframes open question 1 below: the choice may not be "extend
`schema_version` governance to `.md` frontmatter everywhere," but "does a
Chat's structured metadata (tool_calls/footnotes/model, maybe eventually
the ADR-018 compaction-point/summary data too) belong in `.md` at all, or
should it live in its own properly-typed sidecar (JSON, governed by this
ADR's schema mechanism directly, no markdown-embedding tricks needed) next
to a `.md` file that goes back to being just the human-readable
transcript + the Excerpt?" Not decided — a real architecture change (new
file layout, migration of every existing chat `.md` file), not a small
follow-up.

## Open questions (scope — need cservinl's decision)

This narrow instance only versions the chat `prisma:meta` blob, the
newest/freshest format in the codebase and the one that motivated raising
this. Left open:

1. **Extend to vault frontmatter generally** (Notes/Sources/Chats/Streams'
   `---` YAML block)? The dual-format `_parse_frontmatter` HTML-comment/YAML
   acceptance is the same class of problem, just older and already
   papered over a different way — a `schema_version` key in frontmatter
   would let that legacy-acceptance branch eventually be *removed* on
   purpose (once no unversioned/old-format files remain) instead of staying
   forever. Bigger surface: every vault entity's Pydantic model, not just
   one JSON blob.
2. **Chat session structure is server-only — no cross-language transport
   needed for it.** prisma-desktop's sync engine never parses `.md`/`.sess`
   content (confirmed by direct inspection: `push.rs`/`pull.rs` treat every
   file as an opaque byte blob); its role is a webview onto the same web UI
   Python serves, plus byte-level file sync. Even offline chat editing
   routes through a *local* prisma-server, never Rust reconstructing
   session data itself — so `ChatSession`/`SessionMessage`/`RichContent`
   have exactly one implementation, in Python, and stay that way.

   `settings.json` is a separate case: genuinely Rust-only data, no Python
   involvement ever. If it ever needs the same kind of versioned governance
   this ADR built for `prisma:meta`, JSON Schema is the standard,
   well-tooled way to define/validate it — Pydantic v2 exports JSON Schema
   natively (`model.model_json_schema()`, no new Python dependency), and
   Rust has two real, actively-maintained options: the
   [`jsonschema`](https://docs.rs/jsonschema) crate (validates JSON against
   a schema, additive — existing hand-written structs stay as-is) or
   [`typify`](https://docs.rs/typify) (Oxide Computer — generates Rust
   structs directly from a JSON Schema, a bigger change since it replaces
   hand-written structs with generated ones). `jsonschema` (validate-only)
   is the better fit if this is ever built: `settings.json`'s surface is
   small, and a validation guard rail is proportionate to that.

   The generic `schema_gov` Rust module (migration chain + `jsonschema`
   validation wrapper, zero references to any prisma-desktop domain type)
   exists as tested groundwork for exactly that `settings.json` case — not
   because chat sessions need it, since they don't touch Rust at all.
3. **Where does migration *logic* belong for the broader (frontmatter)
   case — inside each Pydantic model via `model_validator(mode="before")`,
   or in the vault-layer parse functions (`vault.py`), like this narrow
   instance?** A `model_validator` keeps migration co-located with the
   model it upgrades (governance the model itself owns, matching
   cservinl's "maybe even pydantic" framing) and applies automatically to
   *any* code path constructing that model from a raw dict, not just the
   one parse function that happens to call it explicitly. The tradeoff:
   several of this codebase's vault entities are assembled from multiple
   pieces (frontmatter dict + parsed body content, e.g. `_parse_chat_body`
   builds `ChatMessage` from a regex match *and* the meta comment, not a
   single raw dict) — a `model_validator(mode="before")` needs one raw
   dict to operate on, which may mean restructuring how a few of these
   parse functions assemble their inputs before construction, not just
   adding a validator.

## Related

- [ADR-017](ADR-017-claim-attribution-and-footnote-model.md) — the
  `prisma:meta` persistence fix this governance was raised in response to.
- `prisma-desktop/src-tauri/src/settings.rs` — the Rust-side instance of
  the same underlying problem (open question 2 above).
