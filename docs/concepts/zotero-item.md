# ZoteroItem

## What it is

A **ZoteroItem** is a full Zotero record — the bookmark layer. It represents a paper, book,
web page, or other reference that Prisma has found and stored in Zotero.

Zotero is a bookmark manager. A `ZoteroItem` means: *I know this exists.* It does not mean
you have read it, analysed it, or are working with it. That distinction is the entire
separation between [ZoteroItem](zotero-item.md) (bookmark) and [Source](source.md) (second brain).

Items live in Zotero — not in the vault. They are accessed via the Zotero local HTTP API
(`localhost:23119`) or the Zotero Web API (`api.zotero.org`).

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
| `collection_keys` | list[str] | Collections this item belongs to |
| `pdf_path` | Path \| None | Local path to attached PDF (if available) |

## Relations

- Belongs to one or more [ZoteroCollection](zotero-collection.md)s.
- Can be promoted to a [Source](source.md) via `POST /zotero/import/{key}`.
  Once promoted, the `Source` has `zotero_key` pointing back to this item.
- Produced by `SearchAgent` as [PaperMetadata](paper-metadata.md), then written to Zotero
  during a stream run.

## The promotion flow

```
ZoteroItem  →  POST /zotero/import/{key}  →  Source (vault)
   (bookmark)       (deliberate action)       (second brain)
```

A user imports a Zotero item into the vault when they decide to actively work with it.
Import does three things:
1. Reads `ZoteroItem` metadata (title, authors, abstract, DOI).
2. Fetches the PDF from Zotero attachment or from the URL (arxiv etc.).
3. Runs docu-craft to produce the `.md` body; saves `Source` with `zotero_key = item.key`.

## Relevant axioms

> Every Source has a `zotero_key`. See [Axiom 11](../ontologia.md).
