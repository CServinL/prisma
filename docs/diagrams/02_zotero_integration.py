"""prisma — Zotero integration (multi-view collection).

Run: .venv/bin/python docs/diagrams/02_zotero_integration.py

Two views in one HTML file (sidebar navigator):
  - Client hierarchy  : ClassMap — ZoteroService -> ZoteroClient (Web API) -> Queue
  - Connection states : StateMap — online / offline

Requires sysatlas >= 0.3.0 (ClassMap + StateMap with C4 routing).
Uses build_xml + render_collection directly to combine different diagram types.

Simplified 2026-07-27: prisma only talks to Zotero via its Web API now (the
former HybridClient/LocalAPIClient/desktop-connector backends only ever read
from Zotero Desktop's local HTTP server on the same machine -- a different
machine's concern than the server -- and were removed). No more "local vs
web" client split, no "degraded" state; just online (Web API reachable) vs
offline (writes queue).
"""
from pathlib import Path
from sysatlas import ClassMap, StateMap
from sysatlas._render import render_collection, build_xml

OUT = Path(__file__).with_suffix(".html")

# ── View 1: Client class hierarchy ────────────────────────────────────────────
c = ClassMap(title="prisma — Zotero client hierarchy")

c.cls("ZoteroService",   kind="class",      label="ZoteroService")
c.cls("UnifiedClient",   kind="interface",  label="UnifiedZoteroClient")
c.cls("WebAPIClient",    kind="class",      label="WebAPIClient")
c.cls("PendingQueue",    kind="class",      label="PendingWriteQueue")

c.method("UnifiedClient",  "save_items",      params=["items: list"], return_type="None")
c.method("UnifiedClient",  "get_collections", return_type="list")
c.method("UnifiedClient",  "get_items",       params=["key: str"],    return_type="list")
c.method("UnifiedClient",  "search",          params=["q: str"],      return_type="list")

c.attribute("WebAPIClient",   "api_key",     type="str")
c.attribute("WebAPIClient",   "user_id",     type="int")
c.method("PendingQueue",      "enqueue",     params=["op: WriteOp"], return_type="None")
c.method("PendingQueue",      "flush",       params=["client"],      return_type="int")
c.method("ZoteroService",     "from_config", params=["cfg"],         return_type="ZoteroService", is_static=True)

c.relate("ZoteroService",  "UnifiedClient",  kind="composition")
c.relate("WebAPIClient",   "UnifiedClient",  kind="implementation")
c.relate("UnifiedClient",  "WebAPIClient",   kind="aggregation",  label="reads/writes",  target_multiplicity="0..1")
c.relate("UnifiedClient",  "PendingQueue",   kind="composition",  label="offline buffer", target_multiplicity="1")

# ── View 2: Connection state machine ──────────────────────────────────────────
s = StateMap(title="prisma — Zotero connection states")

s.initial()
s.state("detecting", label="Detecting",  entry="probe Zotero Web API")
s.state("online",    label="Online",     entry="flush_queue()",  do="web reads/writes")
s.state("offline",   label="Offline",    do="writes -> PendingQueue")
s.final()

s.transition("__initial__", "detecting")
s.transition("detecting",   "online",    event="web ok")
s.transition("detecting",   "offline",   event="web unreachable")
s.transition("online",      "offline",   event="web unreachable",   action="queue writes")
s.transition("offline",     "detecting", event="connectivity restored")
s.transition("online",      "__final__", event="shutdown",          action="persist queue")
s.transition("offline",     "__final__", event="shutdown")

# ── Combine into one HTML via low-level API ───────────────────────────────────
def _xml(m):
    nodes, edges, groups, lo = m._to_architecture()
    return build_xml(nodes, edges, groups, lo, debug=False, strategy="layered")

html = render_collection(
    {"Client hierarchy": _xml(c), "Connection states": _xml(s)},
    title="prisma — Zotero integration",
)
OUT.write_text(html, encoding="utf-8")
print(f"[sysatlas] wrote {OUT}")
