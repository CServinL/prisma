"""ADR-020: one-time backfill of bibliographic fields (journal/volume/
issue/pages/publisher/item_type) onto sources imported before those fields
existed on `Source`, by re-fetching each one from Zotero's API via its
already-stored `zotero_key`. Sources with no `zotero_key` (non-Zotero
origin) or that already have at least one of the new fields (already
backfilled, or imported after this landed) are skipped, not overwritten.
"""
from dataclasses import dataclass

from prisma.integrations.zotero.client import ZoteroClient
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import NodeType


@dataclass
class BackfillResult:
    slug: str
    updated: bool
    error: str | None = None


def backfill_source_metadata(
    vault: VaultService, zotero: ZoteroClient, *, dry_run: bool = True,
) -> list[BackfillResult]:
    results: list[BackfillResult] = []
    for meta in vault.list_nodes(node_type=NodeType.source).sources:
        source = vault.get_source(meta.slug)
        if not source.zotero_key:
            results.append(BackfillResult(slug=source.slug, updated=False, error="no zotero_key on file"))
            continue
        if source.journal or source.publisher or source.item_type:
            results.append(BackfillResult(slug=source.slug, updated=False))
            continue
        item = zotero.get_item(source.zotero_key)
        if item is None:
            results.append(BackfillResult(
                slug=source.slug, updated=False, error="Zotero item not found (deleted/moved?)",
            ))
            continue
        if not dry_run:
            vault.update_source_bibliographic_fields(
                source.slug,
                journal=item.publication_title, volume=item.volume, issue=item.issue,
                pages=item.pages, publisher=item.get_field("publisher"), item_type=item.item_type,
            )
        results.append(BackfillResult(slug=source.slug, updated=True))
    return results
