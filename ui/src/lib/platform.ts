// Tauri-vs-browser platform differences, isolated here so +page.svelte
// doesn't need to branch on isTauri for every settings/scale/shell-open
// call site. Rendered UI differences (window chrome, resize grips) live
// in their own components under lib/components/ instead.
import { invoke } from "@tauri-apps/api/core";

export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export interface SavedServer {
  name: string;
  url: string;
}

// Same defaults as prisma-desktop's own Rust-side Settings::default() —
// kept in sync manually since the two aren't generated from one schema.
export const DEFAULT_SAVED_SERVERS: SavedServer[] = [
  { name: "Local", url: "http://127.0.0.1:8765" },
  // Generic placeholder — never a real maintainer server name/hostname,
  // see docs/wiki/deployment-models.md for real-world examples.
  { name: "Remote", url: "https://prisma.yourdomain.com" },
];

export interface AppSettings {
  scale: number;
  server_url: string;
  saved_servers: SavedServer[];
  // Tauri-only — where the vault-sync engine's local .md mirror lives.
  // null/empty means "use the default location" (see prisma-desktop's
  // settings::resolve_vault_path). Not meaningful in browser/PWA mode,
  // which has no local vault mirror at all.
  vault_path: string | null;
}

// 1x reads as uncomfortably small on today's typical high-density
// displays (confirmed live: 4K monitors at native resolution, both in
// Tauri and in a browser tab) — 1.5x is a more usable out-of-the-box
// default; users can still dial it from 1x-5x in Settings.
export const DEFAULT_SCALE = 1.5;

export async function loadSettings(): Promise<AppSettings> {
  if (isTauri) {
    return invoke<AppSettings>("get_settings");
  }
  const stored = localStorage.getItem("prisma-settings");
  if (stored) {
    const parsed = JSON.parse(stored);
    // Isolated fallback, not a full merge: a browser/PWA install that
    // saved settings before saved_servers existed shouldn't lose its
    // other fields, but also shouldn't silently keep an empty/missing
    // server list forever.
    if (!parsed.saved_servers) parsed.saved_servers = DEFAULT_SAVED_SERVERS;
    return parsed;
  }
  return { scale: DEFAULT_SCALE, server_url: "", saved_servers: DEFAULT_SAVED_SERVERS, vault_path: null };
}

export async function saveSettings(cfg: AppSettings): Promise<void> {
  if (isTauri) {
    await invoke("save_settings_cmd", { settings: cfg });
  } else {
    localStorage.setItem("prisma-settings", JSON.stringify(cfg));
  }
}

export async function applyScale(scale: number): Promise<void> {
  if (isTauri) {
    // Native webview zoom — window.set_zoom on the Rust side. Never
    // affected by the web-only transform:scale() .shell carries (see
    // +page.svelte's :global(html:not(.tauri)) .shell rule), and has none
    // of that mechanism's position:fixed containing-block side effects.
    await invoke("apply_scale", { scale });
  } else if (typeof document !== "undefined") {
    // Consumed by .shell's transform: scale(var(--ui-scale)) + compensating
    // width/height — not CSS `zoom` (confirmed live 2026-07-09: zoom
    // reports scrollHeight/clientHeight in inconsistent unit spaces for
    // the zoomed element itself, letting content scroll past the visible
    // bottom edge) and not a root font-size trick (this UI is built
    // almost entirely with fixed px, not em/rem).
    document.documentElement.style.setProperty("--ui-scale", String(scale));
  }
}

export function shellOpen(url: string): void | Promise<unknown> {
  if (isTauri) return invoke("open_url", { url });
  window.open(url, "_blank");
}

export function winDrag(): void {
  if (isTauri) invoke("window_start_drag");
}

/// Opens a native folder picker for the vault-sync engine's local .md
/// mirror location. Returns null if the user cancelled, or if not
/// running under Tauri at all (no local vault mirror in browser/PWA mode).
export async function pickVaultFolder(): Promise<string | null> {
  if (!isTauri) return null;
  try { return await invoke<string | null>("pick_vault_folder"); } catch { return null; }
}
