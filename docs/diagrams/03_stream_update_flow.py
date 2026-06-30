"""prisma — research stream update sequence.

Run: .venv/bin/python docs/diagrams/03_stream_update_flow.py

Shows the full message flow when a research stream refreshes:
UI trigger → server → agents → Zotero.
"""
from pathlib import Path
from sysatlas import SequenceMap

OUT = Path(__file__).with_suffix(".html")

m = SequenceMap(title="prisma — stream update flow")

m.actor("user",         kind="actor",    label="User / scheduler")
m.actor("api",          kind="boundary", label="FastAPI :8765")
m.actor("stream_mgr",   kind="control",  label="StreamManager")
m.actor("search",       kind="control",  label="SearchAgent")
m.actor("analysis",     kind="control",  label="AnalysisAgent")
m.actor("zotero_agent", kind="control",  label="ZoteroAgent")
m.actor("zotero_svc",   kind="system",   label="ZoteroService")
m.actor("ollama",       kind="system",   label="Ollama (LLM)")
m.actor("ext_apis",     kind="system",   label="arXiv / S2 / Books")

m.send("user",         "api",          label="POST /streams/{slug}/update", order=1)
m.send("api",          "stream_mgr",   label="update_stream(slug)",          order=2)
m.send("stream_mgr",   "search",       label="search(query, sources)",        order=3)
m.send("search",       "ext_apis",     label="HTTP requests",                 order=4, kind="async")
m.send("ext_apis",     "search",       label="PaperMetadata[]",               order=5, kind="reply")
m.send("search",       "stream_mgr",   label="deduplicated results",          order=6, kind="reply")

m.send("stream_mgr",   "analysis",     label="assess_relevance(papers)",      order=7)
m.send("analysis",     "ollama",       label="relevance prompt (batch)",       order=8, kind="async")
m.send("ollama",       "analysis",     label="scores",                         order=9, kind="reply")
m.send("analysis",     "stream_mgr",   label="relevant papers",               order=10, kind="reply")

m.send("stream_mgr",   "analysis",     label="analyze(papers)",               order=11)
m.send("analysis",     "ollama",       label="deep analysis prompt",           order=12, kind="async")
m.send("ollama",       "analysis",     label="AnalysisResult[]",               order=13, kind="reply")
m.send("analysis",     "stream_mgr",   label="AnalysisResult[]",              order=14, kind="reply")

m.send("stream_mgr",   "zotero_agent", label="save_items(papers)",            order=15)
m.send("zotero_agent", "zotero_svc",   label="create_collection / save_items", order=16)
m.frame("opt",  start_order=17, end_order=18, label="offline")
m.send("zotero_svc",   "zotero_agent", label="enqueue (PendingQueue)",         order=17, kind="reply")
m.send("zotero_agent", "stream_mgr",   label="ok (queued)",                    order=18, kind="reply")
m.send("zotero_agent", "stream_mgr",   label="saved",                          order=19, kind="reply")

m.send("stream_mgr",   "api",          label="StreamStatus (updated)",         order=20, kind="reply")
m.send("api",          "user",         label="200 OK + status",               order=21, kind="reply")

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
