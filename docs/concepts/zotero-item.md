# ZoteroItem

## What it is

A **ZoteroItem** is a bookmark in the Zotero library — the record that a paper exists and
was found by one of Prisma's searches. It means: *we know this paper exists.* It does not
mean you have read it, that it is relevant to any particular stream, or that you are working
with it.

The Zotero library is a **shared cache across all streams**. Any stream can discover a paper
and add it to the library. Subsequent streams can find that same paper via library search
instead of hitting external APIs again — it is already enriched with title, abstract, authors,
and possibly an attached PDF.

The collection_keys field shows which streams have accepted this item. Being in the library
with zero collection memberships means: found and bookmarked, but no stream has accepted it
yet (or the LLM gate rejected it for every stream that evaluated it).

## Fields

| Field | Type | Description |
|---|---|---|
| `key` | str | Globally unique Zotero item key |
| `title` | str | Paper or document title |
| `item_type` | str | Zotero item type (journalArticle, preprint, book, etc.) |
| `authors` | list[str] | Author names |
| `year` | int \| None | Publication year |
| `abstract` | str \| None | Abstract |
| `doi` | str \| None | DOI |
| `url` | str \| None | Primary URL |
| `publication` | str \| None | Journal or venue |
| `tags` | list[str] | Zotero tags |
| `collection_keys` | list[str] | Collections (streams) that accepted this item |
| `pdf_path` | Path \| None | Local path to attached PDF (if available) |

## Relations

- Lives in the Zotero library, shared across all streams.
- Belongs to zero or more [ZoteroCollection](zotero-collection.md)s — one per stream that
  accepted it via its LLM relevance gate.
- Can be promoted to a [Source](source.md) via `POST /zotero/import/{key}`.
  Once promoted, the `Source` has `zotero_key` pointing back to this item.
- Created from [PaperMetadata](paper-metadata.md) during the bookmark step of a stream run,
  before the relevance gate is evaluated.
- Also discovered via library search — a stream may find it here instead of from the internet,
  saving an external API call and deduplication work.

## The bookmark-first principle

A paper is saved to the Zotero library as soon as it is discovered via any academic search
(internet or library). The relevance gate comes after. Bookmarking is unconditional —
it reflects discovery, not acceptance.

```
Search result → add_item to Zotero  →  LLM relevance gate  →  add to collection
                 (always, if new)       (per-stream)            (only if relevant)
```

## The promotion flow

When a user decides to actively work with a paper:

```
ZoteroItem  →  POST /zotero/import/{key}  →  Source (vault)
   (bookmark)       (deliberate action)       (second brain)
```

Import reads the ZoteroItem metadata, fetches the PDF if available, runs docu-craft to
produce a `.md` body, and saves a `Source` with `zotero_key = item.key`.

## Relevant axioms

> Bookmark-first. See [Axiom 12](../ontologia.md).
> Relevance is per-stream. See [Axiom 13](../ontologia.md).
> Library search is a first-class source. See [Axiom 14](../ontologia.md).
> Every Source has a `zotero_key`. See [Axiom 11](../ontologia.md).
