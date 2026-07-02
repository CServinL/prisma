"""prisma — GPU/LLM compute-pool topology (ADR-012 addendum).

Run: .venv/bin/python docs/diagrams/07a_compute_pool_topology.py

Split from 06_process_supervision.py to stay within sysatlas's focused-view
guidance (~10 components/view) — this is its own concern (arbitrating one
shared Ollama backend across three independent callers), not process
topology or crash recovery. See 07b_compute_pool_contention.py for the
sequence view of what happens when two callers want different models at
once.
"""
from pathlib import Path
from sysatlas import SystemMap

OUT = Path(__file__).with_suffix(".html")

tp = SystemMap(title="prisma — compute-pool topology")

tp.group("Callers",  color="#0ea5e9", label="Three independent Ollama callers")
tp.group("Arbiter",  color="#f43f5e", label="Supervisor")
tp.group("OnDemand", color="#f59e0b", label="Request-scoped (not supervised)")
tp.group("Backend",  color="#10b981", label="Shared LLM/embedding backend")

tp.add_component("chroma_embeds",     label="ChromaIndexer embed calls",     layer="callers",  group="Callers",  tech="model=nomic-embed-text — inside API process")
tp.add_component("analysis_agent",    label="AnalysisAgent LLM calls",       layer="callers",  group="Callers",  tech="model=llm_config.model — inside API process")
tp.add_component("graphify_launcher", label="GraphifyIndexer._run_graphify",layer="callers",  group="Callers",  tech="holds lease for the whole run, ~2h ceiling")

tp.add_component("graphify_proc",     label="Graphify subprocess",           layer="ondemand", group="OnDemand", tech="spawned only after lease is granted")

tp.add_component("resource_mgr",      label="ResourceManager",               layer="arbiter",  group="Arbiter",  tech="named pools, model_affinity, contention stats (granted/denied_capacity/denied_model_busy)")

tp.add_component("ollama",            label="Ollama",                        layer="backend",  group="Backend",  tech=":11434 — single local GPU, one resident model at a time")

tp.connect("chroma_embeds",     "resource_mgr", label="resource_lock.lease()")
tp.connect("analysis_agent",    "resource_mgr", label="resource_lock.lease()")
tp.connect("graphify_launcher", "resource_mgr", label="resource_lock.lease()")
tp.connect("graphify_launcher", "graphify_proc",label="spawn (holds lease)", style="dashed")

tp.connect("chroma_embeds",     "ollama",       label="embed calls")
tp.connect("analysis_agent",    "ollama",       label="generate calls")
tp.connect("graphify_proc",     "ollama",       label="generate calls")

tp.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
