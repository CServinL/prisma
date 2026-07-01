"""prisma — process supervision (ADR-012).

Run: .venv/bin/python docs/diagrams/06_process_supervision.py

Two views:
  - Topology     : supervisor spawning/monitoring the three worker processes
  - Failure flow : what happens when a worker dies unexpectedly vs. deliberately
"""
from pathlib import Path
from sysatlas import SystemMap

OUT = Path(__file__).with_suffix(".html")

# ── View 1: Topology ───────────────────────────────────────────────────────────
tp = SystemMap(title="prisma — process topology")

tp.group("CLI",        color="#6366f1", label="prisma serve")
tp.group("Supervisor", color="#f43f5e", label="Supervisor (:8760) — stdlib only")
tp.group("Workers",    color="#0ea5e9", label="Supervised workers")
tp.group("OnDemand",   color="#f59e0b", label="Request-scoped (not supervised)")

tp.add_component("cli",          label="prisma serve",       layer="cli",     group="CLI",        tech="click command")
tp.add_component("supervisor",   label="Supervisor",          layer="sup",     group="Supervisor", tech="subprocess.Popen + monitor loop")
tp.add_component("control_api",  label="Control API",         layer="sup",     group="Supervisor", tech="http.server — GET /status, POST /restart/{name}")

tp.add_component("api_proc",     label="API process",         layer="workers", group="Workers",    tech=":8765 — prisma.server.app")
tp.add_component("web_proc",     label="Web process",         layer="workers", group="Workers",    tech=":8766 — prisma.server.web_app")
tp.add_component("chroma_proc",  label="ChromaDB server",     layer="workers", group="Workers",    tech=":8767 — chroma run")

tp.add_component("graphify_proc",label="Graphify subprocess", layer="ondemand",group="OnDemand",   tech="spawned by API's GraphifyIndexer, per run")

tp.connect("cli",        "supervisor",   label="launches")
tp.connect("supervisor", "control_api",  label="exposes")
tp.connect("supervisor", "api_proc",     label="spawn + monitor")
tp.connect("supervisor", "web_proc",     label="spawn + monitor")
tp.connect("supervisor", "chroma_proc",  label="spawn + monitor")
tp.connect("api_proc",   "graphify_proc",label="spawns on demand", style="dashed")
tp.connect("api_proc",   "chroma_proc",  label="HttpClient (embeddings)")

# ── View 2: Failure handling ───────────────────────────────────────────────────
fl = SystemMap(title="prisma — failure & recovery paths")

fl.group("Unexpected", color="#ef4444", label="Unexpected death")
fl.group("Deliberate",  color="#10b981", label="Deliberate restart")
fl.group("Sup",         color="#f43f5e", label="Supervisor")

fl.add_component("crash",        label="Worker crashes",      layer="unexpected", group="Unexpected", tech="e.g. unhandled exception, OOM")
fl.add_component("poll",         label="poll() detects death",layer="unexpected", group="Unexpected", tech="every 2s")
fl.add_component("backoff",      label="Backoff restart",      layer="unexpected", group="Unexpected", tech="1s → 2s → 4s … capped at 30s")

fl.add_component("code_edit",    label="Code edited on disk", layer="deliberate", group="Deliberate", tech="e.g. bug fix in chroma_service.py")
fl.add_component("restart_call", label="POST /restart/{name}",layer="deliberate", group="Deliberate", tech="picks up new code — unlike /reload/*")

fl.add_component("terminate",    label="terminate() → wait()",layer="sup",        group="Sup", tech="SIGTERM, 5s grace")
fl.add_component("kill",         label="kill()",               layer="sup",        group="Sup", tech="SIGKILL if still alive")
fl.add_component("start_new",    label="start()",              layer="sup",        group="Sup", tech="new session, fresh PID")

fl.connect("crash",        "poll")
fl.connect("poll",         "backoff")
fl.connect("backoff",      "start_new",    label="restart")
fl.connect("code_edit",    "restart_call", label="operator triggers")
fl.connect("restart_call", "terminate")
fl.connect("terminate",    "kill",         label="if timeout", style="dashed")
fl.connect("terminate",    "start_new")
fl.connect("kill",         "start_new")

SystemMap.save_collection(
    {"Topology": tp, "Failure & recovery": fl},
    str(OUT),
    title="prisma — process supervision",
)
print(f"[sysatlas] wrote {OUT}")
