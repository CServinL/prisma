"""Shared CORS origin config for the api/web processes (ADR-012 split).

Both processes default to allowing only `tauri://localhost` and any
localhost/127.0.0.1 port (single-machine dev/desktop use). A LAN deployment
where the web and api processes are reachable at different host:port pairs
(e.g. via separate NodePorts) needs the api process to also allow the web
process's origin — supplied via PRISMA_CORS_EXTRA_ORIGINS (comma-separated
full origins, scheme://host:port) rather than hardcoded here, since this
module has no business knowing any specific deployment's hostname.
"""
import os


def extra_origins() -> list[str]:
    raw = os.environ.get("PRISMA_CORS_EXTRA_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]
