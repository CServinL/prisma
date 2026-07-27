# Chat

## What it is

A **Chat** is a saved LLM session grounded in vault nodes. You bring Sources and Notes as
context; the model reasons over them. No external retrieval happens at chat time — the model
only sees what is already in your vault.

Chats are saved as `.md` files in `vault/chats/`. Good excerpts from a chat can be
promoted to [Notes](note.md).

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier |
| `title` | str | Display name |
| `messages` | list[`ChatMessage`] | Full turn history |
| `context_slugs` | list[str] | Vault node slugs used as context for this session |
| `model` | str | Ollama model name used |
| `promoted_excerpts` | list[str] | Note slugs promoted from this chat |

### ChatMessage fields

| Field | Type | Description |
|---|---|---|
| `role` | `ChatRole` | `user` \| `assistant` |
| `content` | str | Message text, with inline superscript footnote markers (e.g. `word¹`) |
| `timestamp` | datetime | |
| `footnotes` | list[[Footnote](footnote.md)] | Per-claim attribution — what kind of sourcing backs each claim, and which document(s) |

## Relations

- Uses [Source](source.md)s and [Note](note.md)s as context (via `context_slugs`).
- Produces [Note](note.md)s via promotion (back-linked on the Note via `promoted_from_chat`).
- Indexed as a [GraphNode](graph-node.md).
- Each assistant `ChatMessage` carries [Footnote](footnote.md)s referencing the `Note`/`Source`
  slugs its claims are attributed to.

## Relevant axioms

> Chats are grounded. A chat uses only vault nodes as context. See [Axiom 5](../ontologia.md).
>
> Claims are footnoted — distinct from grounding, this is about whether each individual claim
> in the output is marked as sourced or as the model's own inference. See
> [Axiom 16](../ontologia.md) and [Footnote](footnote.md).

## Not yet implemented

Chat API routes are not yet implemented. The data model is fully defined.
