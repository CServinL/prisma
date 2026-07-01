"""Prisma Web process — serves the built SvelteKit UI at /app.

Runs independently of the API process (see ADR-012): a crash here doesn't
touch REST/WebSocket traffic, and vice versa. Deliberately does not import
prisma.server.app — pulling that in would drag every API dependency
(chromadb, graphify, zotero, coordinator/agents) into a process whose only
job is serving static files.

Dev-only hot reload: when running from source (ui/src/ exists), a background
thread watches for changes, rebuilds, and bumps a version counter exposed at
GET /ui/dev/version. This is deliberately plain HTTP polling, not pushed over
a WebSocket — it's a self-contained dev convenience local to this process,
with no need to notify the API process or vice versa.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prisma.server.static import CleanUrlStaticFiles

_log = logging.getLogger("prisma.web")

_ui_dist = Path(__file__).parent.parent.parent / "ui" / "build"
_ui_src = Path(__file__).parent.parent.parent / "ui" / "src"
_ui_dir = Path(__file__).parent.parent.parent / "ui"

app = FastAPI(title="Prisma Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mount_ui() -> None:
    if not _ui_dist.exists():
        return
    app.routes[:] = [r for r in app.routes if getattr(r, "name", None) != "ui"]
    app.mount("/app", CleanUrlStaticFiles(directory=_ui_dist, html=True), name="ui")


_mount_ui()


@app.post("/reload/ui")
def reload_ui():
    _mount_ui()
    app.middleware_stack = app.build_middleware_stack()
    return {"status": "reloaded", "ui_dist": str(_ui_dist), "mounted": _ui_dist.exists()}


# ── UI dev watcher (source builds only) ───────────────────────────────────────

_ui_dev_state: dict = {"version": 0, "building": False}
_ui_dev_lock = threading.Lock()


def _src_hash() -> str:
    h = hashlib.md5()
    for root, _, files in os.walk(_ui_src):
        for f in sorted(files):
            try:
                h.update(str(Path(root, f).stat().st_mtime_ns).encode())
            except OSError:
                pass
    return h.hexdigest()


def _ui_watcher() -> None:
    last = _src_hash()
    while True:
        time.sleep(1)
        try:
            cur = _src_hash()
            if cur == last:
                continue
            last = cur
            time.sleep(0.5)  # debounce — let the editor finish writing
            with _ui_dev_lock:
                _ui_dev_state["building"] = True
            _log.info("ui/src changed — rebuilding")
            subprocess.run(["npm", "run", "build"], cwd=_ui_dir, capture_output=True)
            with _ui_dev_lock:
                _ui_dev_state["version"] += 1
                _ui_dev_state["building"] = False
            _log.info("ui rebuild done (version %d)", _ui_dev_state["version"])
        except Exception:
            pass


if _ui_src.exists():
    threading.Thread(target=_ui_watcher, daemon=True, name="ui-watcher").start()


@app.get("/ui/dev/version")
def ui_dev_version():
    with _ui_dev_lock:
        return {"version": _ui_dev_state["version"], "building": _ui_dev_state["building"]}


@app.get("/health")
def health():
    return {"status": "ok"}
