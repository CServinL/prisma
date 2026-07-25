// ADR-011 password-mode auth, client side. Isolated here for the same
// reason as platform.ts: +page.svelte shouldn't branch on isTauri for
// every network call. Under Tauri, login goes through the `sync_login`
// command so a single password prompt covers both this app's own
// authFetch calls AND the Rust sync engine's session (see
// prisma-desktop's src-tauri/src/auth/mod.rs) — pure-browser/PWA use
// falls back to calling POST /auth/login directly.
//
// Reactive UI state (whether to show the login screen) intentionally
// lives in +page.svelte itself, not here — this module only holds a
// plain, non-reactive token so apiFetch can read the current value
// without every call site threading it through by hand, matching how
// platform.ts stays a plain utility module with no component state of
// its own.
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./platform";

let token: string | null = null;
let onAuthRequired: (() => void) | null = null;

export function setAuthRequiredHandler(cb: () => void): void {
  onAuthRequired = cb;
}

/// Called once at startup: on Tauri, picks up a session already stored in
/// auth.json (from a previous run) without reprompting for a password.
/// Returns true if a session was restored.
export async function restoreSession(serverUrl: string): Promise<boolean> {
  if (!isTauri) return false;
  try {
    const status = await invoke<{ logged_in: boolean; token: string | null }>("sync_status", {
      serverUrl,
    });
    if (status.logged_in && status.token) {
      token = status.token;
      return true;
    }
  } catch {
    // sync_status unreachable — treat as "no stored session".
  }
  return false;
}

export async function login(serverUrl: string, password: string): Promise<void> {
  if (isTauri) {
    const result = await invoke<{ token: string; expires_at: string }>("sync_login", {
      serverUrl,
      password,
    });
    token = result.token;
  } else {
    const resp = await fetch(`${serverUrl.replace(/\/$/, "")}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(`login failed (${resp.status}): ${detail}`);
    }
    const body = await resp.json();
    token = body.token;
  }
}

export function logout(serverUrl: string): void {
  token = null;
  if (isTauri) void invoke("sync_logout", { serverUrl }).catch(() => {});
}

export function hasSession(): boolean {
  return token !== null;
}

/// For the one call site that can't go through apiFetch: the browser's
/// native WebSocket API takes subprotocols, not headers — see connectWS()
/// in +page.svelte, which mirrors prisma-desktop's own pull.rs handshake
/// (["bearer", "<jwt>"]).
export function getToken(): string | null {
  return token;
}

/// Drop-in replacement for `fetch()` against apiBase-rooted URLs: attaches
/// `Authorization: Bearer` when a token is held, and invokes the
/// registered handler on a 401 so the UI can show the login screen
/// instead of silently failing every subsequent call. Not used for
/// webBase (static UI assets) or the loopback-only supervisor port — see
/// the vault-sync plan for why those two are out of scope for this
/// gating.
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(url, { ...init, headers });
  if (resp.status === 401) {
    onAuthRequired?.();
  }
  return resp;
}
