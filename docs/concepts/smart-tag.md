# SmartTag

## What it is

A **SmartTag** is a label automatically applied to a [ZoteroItem](zotero-item.md) or
[Source](source.md) during ingestion, based on content analysis. SmartTags categorise
items by temporal position, methodology, quality signal, or research status — without the
user having to tag manually.

## Fields

| Field | Type | Description |
|---|---|---|
| `name` | str | Tag value |
| `category` | `TagCategory` | Classification of the tag type |
| `auto_generated` | bool | `True` for SmartTags; `False` for manually applied tags |
| `description` | str \| None | Why this tag was applied |

## Tag categories

| Category | Examples |
|---|---|
| `prisma` | Internal Prisma labels (`prisma-stream`, `prisma-reviewed`) |
| `temporal` | `recent-2024`, `foundational-pre-2010` |
| `methodology` | `empirical`, `survey`, `theoretical`, `benchmark` |
| `status` | `to-read`, `in-progress`, `archived` |
| `quality` | `high-citation`, `peer-reviewed`, `preprint` |
| `source` | `arxiv`, `semanticscholar`, `pubmed` |

## Relations

- Applied to [ZoteroItem](zotero-item.md)s during stream runs.
- Inherited by [Source](source.md) if the item is later imported to the vault.
- Surface in [GraphNode](graph-node.md) as indexable labels.

## Not yet implemented

SmartTag generation is not yet applied during stream runs or Zotero import.
The `TagCategory` enum and `SmartTag` model are defined in the ontology;
code support is deferred.
