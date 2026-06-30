"""prisma — vault data model (ER diagram).

Run: .venv/bin/python docs/diagrams/04_vault_data_model.py

Shows the logical data model of the vault: notes, sources, chats, streams,
and their relationships. Stored as Markdown files — no database.
"""
from pathlib import Path
from sysatlas import ERMap

OUT = Path(__file__).with_suffix(".html")

m = ERMap(title="prisma — vault data model")

# Entities
m.entity("VaultNote",   label="Note")
m.entity("Source",      label="Source")
m.entity("Chat",        label="Chat")
m.entity("Stream",      label="ResearchStream")
m.entity("ZoteroItem",  label="ZoteroItem")
m.entity("Collection",  label="ZoteroCollection")
m.entity("Tag",         label="Tag")
m.entity("Report",      label="Report")

# VaultNote
m.attribute("VaultNote", "slug",       type="str",  is_key=True,      is_required=True)
m.attribute("VaultNote", "title",      type="str",                    is_required=True)
m.attribute("VaultNote", "content",    type="Markdown",               is_required=True)
m.attribute("VaultNote", "created_at", type="datetime",               is_required=True)
m.attribute("VaultNote", "node_type",  type="note|source|chat|stream",is_required=True)

# Source
m.attribute("Source",   "slug",        type="str",  is_key=True,      is_required=True)
m.attribute("Source",   "url",         type="str")
m.attribute("Source",   "zotero_key",  type="str")
m.attribute("Source",   "quality",     type="SourceQuality")

# Chat
m.attribute("Chat",     "slug",        type="str",  is_key=True,      is_required=True)
m.attribute("Chat",     "messages",    type="JSON[]",                 is_required=True)
m.attribute("Chat",     "model",       type="str")

# Stream
m.attribute("Stream",   "slug",        type="str",  is_key=True,      is_required=True)
m.attribute("Stream",   "query",       type="str",                    is_required=True)
m.attribute("Stream",   "status",      type="active|paused|error",    is_required=True)
m.attribute("Stream",   "next_update", type="datetime")
m.attribute("Stream",   "collection_key", type="str")
m.attribute("Stream",   "refresh_frequency", type="daily|weekly|manual")

# ZoteroItem
m.attribute("ZoteroItem", "key",       type="str",  is_key=True,      is_required=True)
m.attribute("ZoteroItem", "title",     type="str",                    is_required=True)
m.attribute("ZoteroItem", "item_type", type="journalArticle|book|…")
m.attribute("ZoteroItem", "doi",       type="str")
m.attribute("ZoteroItem", "year",      type="int")

# Collection
m.attribute("Collection", "key",       type="str",  is_key=True,      is_required=True)
m.attribute("Collection", "name",      type="str",                    is_required=True)
m.attribute("Collection", "parent_key",type="str")

# Tag
m.attribute("Tag", "name",             type="str",  is_key=True,      is_required=True)

# Report
m.attribute("Report",   "slug",        type="str",  is_key=True,      is_required=True)
m.attribute("Report",   "stream_slug", type="str",                    is_required=True)
m.attribute("Report",   "generated_at",type="datetime",               is_required=True)

# Relationships
m.relate("Stream",     "Collection", "owns",       source_card="1",    target_card="0..1")
m.relate("Collection", "ZoteroItem", "contains",   source_card="1",    target_card="*")
m.relate("Source",     "ZoteroItem", "mirrors",    source_card="0..1", target_card="1")
m.relate("VaultNote",  "Tag",        "tagged with",source_card="*",    target_card="*")
m.relate("Stream",     "Report",     "generates",  source_card="1",    target_card="*")
m.relate("Stream",     "VaultNote",  "stored as",  source_card="1",    target_card="1",  is_identifying=True)
m.relate("Source",     "VaultNote",  "stored as",  source_card="1",    target_card="1",  is_identifying=True)
m.relate("Chat",       "VaultNote",  "stored as",  source_card="1",    target_card="1",  is_identifying=True)

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
