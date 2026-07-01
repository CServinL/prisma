"""prisma — transport layer and authentication (multi-view).

Run: .venv/bin/python docs/diagrams/05_transport_auth.py

Two views:
  - Transport  : REST vs WebSocket — what uses each and why
  - Auth zones : network zones, auth modes, reverse proxy topology
"""
from pathlib import Path
from sysatlas import SystemMap

OUT = Path(__file__).with_suffix(".html")

# ── View 1: Transport layer ────────────────────────────────────────────────────
tr = SystemMap(title="prisma — transport layer")

tr.group("Clients",   color="#6366f1", label="Clients (Tauri / Browser / PWA)")
tr.group("REST",      color="#0ea5e9", label="REST — HTTP (request / response)")
tr.group("WS",        color="#10b981", label="WebSocket /ws (persistent, server push)")
tr.group("Static",    color="#f59e0b", label="Static & binary (HTTP only)")

tr.add_component("client",        label="Client",             layer="client",   group="Clients", tech="fetch() + WebSocket")
tr.add_component("svc_worker",    label="Service Worker",     layer="client",   group="Clients", tech="Workbox offline cache")

tr.add_component("notes_api",     label="Notes CRUD",         layer="rest",     group="REST",    tech="GET/POST/PUT/DELETE /notes")
tr.add_component("search_api",    label="Search",             layer="rest",     group="REST",    tech="GET /search, /search/deep")
tr.add_component("streams_api",   label="Streams",            layer="rest",     group="REST",    tech="GET/POST/PATCH /streams")
tr.add_component("zotero_api",    label="Zotero",             layer="rest",     group="REST",    tech="GET/POST /zotero/*")
tr.add_component("status_api",    label="Status / Health",    layer="rest",     group="REST",    tech="GET /status, /health")
tr.add_component("reload_api",    label="Reload endpoints",   layer="rest",     group="REST",    tech="POST /reload/*")

tr.add_component("ws_push",       label="Server push events", layer="ws",       group="WS",      tech="vault_change | hot_reload | stream_progress")
tr.add_component("ws_fallback",   label="Polling fallback",   layer="ws",       group="WS",      tech="GET /ui/dev/version (when WS blocked)")

tr.add_component("ui_static",     label="SvelteKit app",      layer="static",   group="Static",  tech="GET /app/* (StaticFiles)")
tr.add_component("vault_assets",  label="Vault assets",       layer="static",   group="Static",  tech="GET /vault/assets/* (FileResponse)")
tr.add_component("manifest",      label="PWA manifest",       layer="static",   group="Static",  tech="GET /app/manifest.webmanifest")

tr.connect("client",     "notes_api",    label="fetch()")
tr.connect("client",     "search_api",   label="fetch()")
tr.connect("client",     "streams_api",  label="fetch()")
tr.connect("client",     "zotero_api",   label="fetch()")
tr.connect("client",     "status_api",   label="fetch()")
tr.connect("client",     "reload_api",   label="fetch()")
tr.connect("client",     "ws_push",      label="new WebSocket()")
tr.connect("client",     "ui_static",    label="browser loads")
tr.connect("client",     "vault_assets", label="img/pdf src=")
tr.connect("client",     "manifest",     label="PWA install")
tr.connect("svc_worker", "ui_static",    label="cache-first")
tr.connect("ws_push",    "ws_fallback",  label="fallback if blocked", style="dashed")

# ── View 2: Auth zones ─────────────────────────────────────────────────────────
az = SystemMap(title="prisma — auth zones")

az.group("Local",     color="#10b981", label="Local zone (loopback)")
az.group("LAN",       color="#f59e0b", label="LAN zone (RFC1918)")
az.group("WAN",       color="#ef4444", label="WAN zone (public internet)")
az.group("Server",    color="#0ea5e9", label="prisma serve")
az.group("Proxy",     color="#6366f1", label="Reverse proxy")
az.group("Edge",      color="#64748b", label="Cloudflare edge")

az.add_component("local_client",  label="Local client",      layer="local",  group="Local",  tech="127.0.0.1 — Tauri / browser (dev)")
az.add_component("lan_client",    label="LAN client",        layer="lan",    group="LAN",    tech="192.168.x.x — desktop / mobile PWA")
az.add_component("wan_client",    label="WAN client",        layer="wan",    group="WAN",    tech="public IP — mobile / remote")

az.add_component("zone_mw",       label="Zone middleware",   layer="server", group="Server", tech="classifies IP → applies auth")
az.add_component("no_auth",       label="No auth",           layer="server", group="Server", tech="loopback → pass through")
az.add_component("pw_auth",       label="Password auth",     layer="server", group="Server", tech="bcrypt hash → JWT session")
az.add_component("oidc_auth",     label="OIDC auth",         layer="server", group="Server", tech="Google / Zitadel / Authentik")

az.add_component("caddy",         label="Caddy",             layer="proxy",  group="Proxy",  tech="TLS termination + DNS-01 cert")
az.add_component("dnsmasq",       label="dnsmasq (LAN DNS)", layer="proxy",  group="Proxy",  tech="split-horizon: domain → local IP")

az.add_component("cf_edge",       label="Cloudflare edge",   layer="edge",   group="Edge",   tech="TLS + CF-Connecting-IP header")
az.add_component("duckdns",       label="DuckDNS",           layer="edge",   group="Edge",   tech="dynamic DNS → home IPv6")

az.connect("local_client", "zone_mw",    label="127.0.0.1")
az.connect("lan_client",   "dnsmasq",    label="DNS query")
az.connect("dnsmasq",      "caddy",      label="→ local IP")
az.connect("lan_client",   "caddy",      label="HTTPS (LAN cert)")
az.connect("caddy",        "zone_mw",    label="X-Forwarded-For (LAN IP)")
az.connect("wan_client",   "cf_edge",    label="HTTPS")
az.connect("duckdns",      "cf_edge",    label="IPv6 record")
az.connect("cf_edge",      "zone_mw",    label="CF-Connecting-IP (public IP)")
az.connect("zone_mw",      "no_auth",    label="loopback")
az.connect("zone_mw",      "pw_auth",    label="RFC1918")
az.connect("zone_mw",      "oidc_auth",  label="public IP")

SystemMap.save_collection(
    {"Transport layer": tr, "Auth zones": az},
    str(OUT),
    title="prisma — transport & auth",
)
print(f"[sysatlas] wrote {OUT}")
