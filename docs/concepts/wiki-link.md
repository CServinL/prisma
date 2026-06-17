# WikiLink

## What it is

A **WikiLink** is a navigational link from one vault node to another, written as `[[slug]]`
or `[[slug#section]]` in markdown bodies. The renderer resolves it server-side before
producing HTML.

If the target slug does not exist in the vault, the link is marked `resolved = False`
and rendered as a visible broken-link warning.

## Notation

| Notation | Meaning |
|---|---|
| `[[slug]]` | Link to the node with this slug |
| `[[slug#section]]` | Link to a specific heading section |
| `[[slug\|Display text]]` | Link with custom label |

## Fields

| Field | Type | Description |
|---|---|---|
| `source_slug` | str | Node containing the link |
| `target_slug` | str | Node being linked to |
| `section` | str \| None | Heading anchor in the target |
| `resolved` | bool | `False` if the target slug does not exist |

## Relations

- Appears in the body of [Note](note.md), [Source](source.md), or [Chat](chat.md).
- Becomes a directed edge in the [GraphNode](graph-node.md) graph.
- Broken WikiLinks are surfaced in `RenderedNode.broken_links`.

## Relevant axioms

> Broken citations surface. See [Axiom 6](../ontologia.md).
> `slug` is stable. See [Axiom 9](../ontologia.md).
