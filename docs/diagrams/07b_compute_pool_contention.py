"""prisma — compute-pool contention (ADR-012 addendum).

Run: .venv/bin/python docs/diagrams/07b_compute_pool_contention.py

What actually happens when two callers want different models on the same
GPU at once — a real scenario observed live in supervisor.log (see
docs/ollama-concurrency.md): Graphify holds the pool for its extraction
model, ChromaDB's embed call is denied (409) and retries with backoff, then
succeeds once Graphify releases. See 07a_compute_pool_topology.py for the
static topology this sequence plays out on.
"""
from pathlib import Path
from sysatlas import SequenceMap

OUT = Path(__file__).with_suffix(".html")

sq = SequenceMap(title="prisma — pool contention (a different model wants in)")

sq.actor("graphify", kind="control",  label="Graphify (holder)")
sq.actor("chroma",   kind="control",  label="ChromaIndexer")
sq.actor("sup",      kind="boundary", label="Supervisor :8760")
sq.actor("ollama",   kind="system",   label="Ollama")

sq.send("graphify", "sup",      label="acquire(model=graphify_model)",              order=1)
sq.send("sup",      "graphify", label="granted — pool idle, becomes resident model", order=2, kind="reply")
sq.send("graphify", "ollama",   label="extraction chunk 1/24",                       order=3, kind="async")

sq.send("chroma",   "sup",      label="acquire(model=nomic-embed-text)",             order=4)
sq.send("sup",      "chroma",   label="409 — pool busy with a different model",      order=5, kind="reply")
sq.frame("loop", start_order=6, end_order=9, label="backoff retry, up to max_wait=10s")
sq.send("chroma",   "sup",      label="acquire (retry)",                             order=6)
sq.send("sup",      "chroma",   label="409",                                         order=7, kind="reply")
sq.send("chroma",   "sup",      label="acquire (retry)",                             order=8)
sq.send("sup",      "chroma",   label="409 — still busy, give up for this cycle",    order=9, kind="reply")

sq.send("graphify", "sup",      label="release (run complete)",                      order=10)
sq.send("chroma",   "sup",      label="acquire (next incremental tick)",             order=11)
sq.send("sup",      "chroma",   label="granted — pool now idle",                     order=12, kind="reply")
sq.send("chroma",   "ollama",   label="embed calls",                                 order=13, kind="async")

sq.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
