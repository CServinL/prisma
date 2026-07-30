"""prisma — research stream update sequence.

Run: .venv/bin/python docs/diagrams/03_stream_update_flow.py

Shows the full message flow when a research stream refreshes:
UI trigger → server → stream_runner → agents/Zotero. This is the live
implementation (prisma/services/stream_runner.py::run_stream) — the vault's
Markdown-backed Stream, not the removed ResearchStreamManager/Zotero-Collection
JSON-file system this diagram used to (incorrectly) describe.
"""
from pathlib import Path
from sysatlas import SequenceMap

OUT = Path(__file__).with_suffix(".html")

m = SequenceMap(title="prisma — stream update flow")

m.actor("user",         kind="actor",    label="User / scheduler")
m.actor("api",          kind="boundary", label="FastAPI :8765")
m.actor("runner",       kind="control",  label="stream_runner.run_stream")
m.actor("search",       kind="control",  label="SearchAgent")
m.actor("analysis",     kind="control",  label="AnalysisAgent")
m.actor("vault",        kind="system",   label="VaultService")
m.actor("zotero_svc",   kind="system",   label="ZoteroClient")
m.actor("ext_apis",     kind="system",   label="arXiv / S2 / PubMed / IEEE / …")

m.send("user",     "api",      label="POST /streams/{slug}/run",              order=1)
m.send("api",      "runner",   label="run_stream(slug, vault, zotero, force)", order=2)

m.send("runner",   "search",   label="preflight + search(query, sources)",    order=3)
m.send("search",   "ext_apis", label="HTTP requests",                          order=4, kind="async")
m.send("ext_apis", "search",   label="PaperMetadata[]",                        order=5, kind="reply")
m.send("search",   "runner",   label="SearchResult (papers)",                  order=6, kind="reply")

m.send("runner",   "zotero_svc", label="ensure_collection / get_collection_items (dedup index)", order=7)
m.send("runner",   "zotero_svc", label="search_items(query) — library source",  order=8)

m.send("runner",   "analysis", label="batch_relevance_check(library candidates)", order=9)
m.send("analysis", "runner",   label="relevance flags",                        order=10, kind="reply")
m.send("runner",   "zotero_svc", label="add_item_to_collection (per relevant item)", order=11)

m.send("runner",   "zotero_svc", label="find_by_identifier / add_paper — bookmark internet papers", order=12)
m.send("runner",   "analysis", label="batch_relevance_check(internet papers)", order=13)
m.send("analysis", "runner",   label="relevance flags",                        order=14, kind="reply")
m.send("runner",   "zotero_svc", label="add_item_to_collection (per relevant item)", order=15)

m.frame("opt", start_order=16, end_order=16, label="Zotero offline")
m.send("zotero_svc", "runner", label="unavailable — papers found but not saved", order=16, kind="reply")

m.send("runner",   "vault",  label="save_stream(last_updated, next_update, total_papers)", order=17)
m.send("runner",   "api",    label="StreamRunResult",                          order=18, kind="reply")
m.send("api",      "user",   label="200 OK + result",                          order=19, kind="reply")

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
