"""prisma — Zotero integration class hierarchy + state machine.

Run: .venv/bin/python docs/diagrams/02_zotero_integration.py

Two diagrams saved as separate files:
  - 02_zotero_integration_classes.html  — client class hierarchy
  - 02_zotero_integration_state.html    — online/offline/degraded state machine
"""
from pathlib import Path
from sysatlas import ClassMap, StateMap

BASE = Path(__file__).parent

# ── Class hierarchy ───────────────────────────────────────────────────────────
c = ClassMap(title="prisma — Zotero client hierarchy")

c.cls("UnifiedClient",    kind="interface",  label="UnifiedZoteroClient")
c.cls("HybridClient",     kind="class",      label="HybridZoteroClient")
c.cls("LocalAPIClient",   kind="class",      label="ZoteroLocalAPIClient")
c.cls("DesktopClient",    kind="class",      label="ZoteroDesktopClient")
c.cls("WebAPIClient",     kind="class",      label="ZoteroWebClient")
c.cls("PendingQueue",     kind="class",      label="PendingWriteQueue")
c.cls("ZoteroService",    kind="class",      label="ZoteroService")

c.method("UnifiedClient", "save_items",    params=["items: list[ZoteroItem]"], return_type="None")
c.method("UnifiedClient", "get_collections", return_type="list[ZoteroCollection]")
c.method("UnifiedClient", "get_items",     params=["collection_key: str"], return_type="list[ZoteroItem]")
c.method("UnifiedClient", "search",        params=["query: str"], return_type="list[ZoteroItem]")

c.attribute("HybridClient", "local",  type="LocalAPIClient")
c.attribute("HybridClient", "web",    type="WebAPIClient | None")
c.attribute("HybridClient", "queue",  type="PendingWriteQueue")
c.method("HybridClient",    "is_online",   return_type="bool")
c.method("HybridClient",    "flush_queue", return_type="None")

c.attribute("LocalAPIClient",  "base_url",   type="str")
c.attribute("WebAPIClient",    "api_key",    type="str")
c.attribute("WebAPIClient",    "user_id",    type="int")
c.attribute("PendingQueue",    "queue_path", type="Path")
c.method("PendingQueue",       "enqueue",    params=["op: WriteOp"], return_type="None")
c.method("PendingQueue",       "flush",      params=["client: UnifiedClient"], return_type="int")

c.attribute("ZoteroService",   "client",     type="HybridClient")
c.method("ZoteroService",      "from_config", params=["cfg: ZoteroConfig"], return_type="ZoteroService", is_static=True)

c.relate("HybridClient",   "UnifiedClient", kind="implementation")
c.relate("LocalAPIClient", "UnifiedClient", kind="implementation")
c.relate("WebAPIClient",   "UnifiedClient", kind="implementation")
c.relate("HybridClient",   "LocalAPIClient", kind="composition", label="reads")
c.relate("HybridClient",   "WebAPIClient",   kind="aggregation",  label="writes")
c.relate("HybridClient",   "PendingQueue",   kind="composition",  label="buffers offline writes")
c.relate("ZoteroService",  "HybridClient",   kind="composition")

c.save(str(BASE / "02a_zotero_classes.html"))
print(f"[sysatlas] wrote 02a_zotero_classes.html")

# ── State machine ─────────────────────────────────────────────────────────────
s = StateMap(title="prisma — Zotero connection state machine")

s.initial()
s.state("detecting",  label="Detecting")
s.state("online",     label="Online\n(local + web)", entry="flush pending queue")
s.state("degraded",   label="Degraded\n(local only)", do="reads via local API")
s.state("offline",    label="Offline\n(no Zotero)", do="writes → PendingQueue")
s.final()

s.transition("__initial__", "detecting")
s.transition("detecting",   "online",    event="local reachable AND web reachable")
s.transition("detecting",   "degraded",  event="local reachable, web unreachable")
s.transition("detecting",   "offline",   event="local unreachable")
s.transition("online",      "degraded",  event="web API error / 429",  action="stop writes, keep reads")
s.transition("online",      "offline",   event="local unreachable",    action="queue writes")
s.transition("degraded",    "online",    event="web reachable",        action="flush queue")
s.transition("degraded",    "offline",   event="local unreachable",    action="queue writes")
s.transition("offline",     "detecting", event="connectivity restored")
s.transition("online",      "__final__", event="server shutdown",      action="persist pending queue")
s.transition("degraded",    "__final__", event="server shutdown")
s.transition("offline",     "__final__", event="server shutdown")

s.save(str(BASE / "02b_zotero_state.html"))
print(f"[sysatlas] wrote 02b_zotero_state.html")
