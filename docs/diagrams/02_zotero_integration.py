"""prisma — Zotero integration (multi-view collection).

Run: .venv/bin/python docs/diagrams/02_zotero_integration.py

Two views in one HTML file (sidebar navigator):
  - Client hierarchy  : ClassMap — ZoteroService -> HybridClient -> Local/Web/Queue
  - Connection states : StateMap — startup / online / degraded / offline

Requires sysatlas >= 0.3.0 (ClassMap + StateMap with C4 routing).
Uses build_xml + render_collection directly to combine different diagram types.
"""
from pathlib import Path
from sysatlas import ClassMap, StateMap
from sysatlas._render import render_collection, build_xml

OUT = Path(__file__).with_suffix(".html")

# ── View 1: Client class hierarchy ────────────────────────────────────────────
c = ClassMap(title="prisma — Zotero client hierarchy")

c.cls("ZoteroService",   kind="class",      label="ZoteroService")
c.cls("UnifiedClient",   kind="interface",  label="UnifiedZoteroClient")
c.cls("HybridClient",    kind="class",      label="HybridZoteroClient")
c.cls("LocalAPIClient",  kind="class",      label="LocalAPIClient")
c.cls("WebAPIClient",    kind="class",      label="WebAPIClient")
c.cls("PendingQueue",    kind="class",      label="PendingWriteQueue")

c.method("UnifiedClient",  "save_items",      params=["items: list"], return_type="None")
c.method("UnifiedClient",  "get_collections", return_type="list")
c.method("UnifiedClient",  "get_items",       params=["key: str"],    return_type="list")
c.method("UnifiedClient",  "search",          params=["q: str"],      return_type="list")

c.attribute("HybridClient",   "local",  type="LocalAPIClient")
c.attribute("HybridClient",   "web",    type="WebAPIClient | None")
c.attribute("HybridClient",   "queue",  type="PendingWriteQueue")
c.method("HybridClient",      "is_online",   return_type="bool")
c.method("HybridClient",      "flush_queue", return_type="None")

c.attribute("LocalAPIClient", "base_url",    type="str")
c.attribute("WebAPIClient",   "api_key",     type="str")
c.attribute("WebAPIClient",   "user_id",     type="int")
c.method("PendingQueue",      "enqueue",     params=["op: WriteOp"], return_type="None")
c.method("PendingQueue",      "flush",       params=["client"],      return_type="int")
c.method("ZoteroService",     "from_config", params=["cfg"],         return_type="ZoteroService", is_static=True)

c.relate("ZoteroService",  "HybridClient",   kind="composition")
c.relate("HybridClient",   "UnifiedClient",  kind="implementation")
c.relate("LocalAPIClient", "UnifiedClient",  kind="implementation")
c.relate("WebAPIClient",   "UnifiedClient",  kind="implementation")
c.relate("HybridClient",   "LocalAPIClient", kind="composition",  label="reads",          target_multiplicity="1")
c.relate("HybridClient",   "WebAPIClient",   kind="aggregation",  label="writes",         target_multiplicity="0..1")
c.relate("HybridClient",   "PendingQueue",   kind="composition",  label="offline buffer", target_multiplicity="1")

# ── View 2: Connection state machine ──────────────────────────────────────────
s = StateMap(title="prisma — Zotero connection states")

s.initial()
s.state("detecting", label="Detecting",  entry="probe :23119 + web API")
s.state("online",    label="Online",     entry="flush_queue()",  do="local + web reads/writes")
s.state("degraded",  label="Degraded",   do="reads via local only")
s.state("offline",   label="Offline",    do="writes -> PendingQueue")
s.final()

s.transition("__initial__", "detecting")
s.transition("detecting",   "online",    event="local ok  web ok")
s.transition("detecting",   "degraded",  event="local ok  web fail")
s.transition("detecting",   "offline",   event="local fail")
s.transition("online",      "degraded",  event="web error / 429",   action="pause writes")
s.transition("online",      "offline",   event="local unreachable", action="queue writes")
s.transition("degraded",    "online",    event="web reachable",     action="flush queue")
s.transition("degraded",    "offline",   event="local unreachable", action="queue writes")
s.transition("offline",     "detecting", event="connectivity restored")
s.transition("online",      "__final__", event="shutdown",          action="persist queue")
s.transition("degraded",    "__final__", event="shutdown")
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
