// Tauri-vs-browser platform differences, isolated here so +page.svelte
// doesn't need to branch on isTauri for every settings/scale/shell-open
// call site. Rendered UI differences (window chrome, resize grips) live
// in their own components under lib/components/ instead.
import { invoke } from "@tauri-apps/api/core";

export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export interface AppSettings {
  scale: number;
  hostname: string;
  tls: boolean;
  api_port: number;
  web_port: number;
  // Tauri-only — where the vault-sync engine's local .md mirror lives.
  // null/empty means "use the default location" (see prisma-desktop's
  // settings::resolve_vault_path). Not meaningful in browser/PWA mode,
  // which has no local vault mirror at all.
  vault_path: string | null;
  // Width in px of the resizable split between the nav pane and the main
  // viewport. Round-tripped through this same store (settings.json in
  // Tauri, the "prisma-settings" localStorage key in browser/PWA) rather
  // than its own ad hoc key, same as every other layout preference here.
  sidebar_width: number;
}

// Same derivation as prisma-desktop's own Rust-side Settings::api_url().
export function apiUrl(cfg: Pick<AppSettings, "hostname" | "tls" | "api_port">): string {
  return `${cfg.tls ? "https" : "http"}://${cfg.hostname}:${cfg.api_port}`;
}

// 1x reads as uncomfortably small on today's typical high-density
// displays (confirmed live: 4K monitors at native resolution, both in
// Tauri and in a browser tab) — 1.5x is a more usable out-of-the-box
// default; users can still dial it from 1x-5x in Settings.
export const DEFAULT_SCALE = 1.5;

// Same default as prisma-desktop's own Rust-side default_sidebar_width().
export const DEFAULT_SIDEBAR_WIDTH = 220;

export async function loadSettings(): Promise<AppSettings> {
  if (isTauri) {
    return invoke<AppSettings>("get_settings");
  }
  const stored = localStorage.getItem("prisma-settings");
  if (stored) {
    return JSON.parse(stored);
  }
  return {
    scale: DEFAULT_SCALE, hostname: "", tls: false, api_port: 0, web_port: 0,
    vault_path: null, sidebar_width: DEFAULT_SIDEBAR_WIDTH,
  };
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

/// Opens a native folder picker for the vault-sync engine's local .md
/// mirror location. Returns null if the user cancelled, or if not
/// running under Tauri at all (no local vault mirror in browser/PWA mode).
export async function pickVaultFolder(): Promise<string | null> {
  if (!isTauri) return null;
  try { return await invoke<string | null>("pick_vault_folder"); } catch { return null; }
}
