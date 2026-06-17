# Citation

## What it is

A **Citation** is a reference to a [Source](source.md) by its citekey, written as
`[[@citekey]]` in note and chat bodies. The renderer resolves it to the source's vault node.

If the citekey has no matching `Source` in the vault, the citation is marked `resolved = False`
and rendered as a visible warning. This is intentional — unresolved citations must surface.

Citations create the scholarly connection between personal synthesis ([Note](note.md), [Chat](chat.md))
and the primary literature ([Source](source.md)).

## Notation

| Notation | Meaning |
|---|---|
| `[[@smith2024]]` | Cite the source with `citekey = smith2024` |
| `[[@smith2024, p. 42]]` | Citation with a page locator (display only) |

## Fields

| Field | Type | Description |
|---|---|---|
| `source_slug` | str | Note or chat containing the citation |
| `citekey` | str | Must match `Source.citekey` |
| `resolved` | bool | `False` if no Source has this citekey |

## Citekey format

Citekeys are generated at import time from author last name + year: `vaswani2017`.
For unknown authors: `<first-title-word><year>`. Citekeys are globally unique within the vault.

## Relations

- Appears in [Note](note.md) and [Chat](chat.md) bodies.
- Resolved against [Source](source.md)s at render time.
- Creates a citation edge in the [GraphNode](graph-node.md) graph.
- Broken citations appear in `RenderedNode.broken_citations`.

## Relevant axioms

> Broken citations surface. See [Axiom 6](../ontologia.md).
