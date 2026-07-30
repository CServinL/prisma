// Vault-sync engine controls (prisma-desktop's Rust src-tauri/src/sync/) —
// Tauri-only, mirrors auth.ts's isTauri-gated pattern. See the vault-sync
// plan: only the Tauri build gets a local vault mirror at all.
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./platform";

export function isLoopbackUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "::1";
  } catch {
    return true; // malformed URL — safer to not sync against it
  }
}

export interface SyncStatusInfo {
  running: boolean;
  server_url: string | null;
  vault_path: string | null;
  tracked_files: number;
  // True when the running engine's WS connection is being rejected as
  // unauthorized (expired/invalid token) — distinct from an ordinary
  // outage, which looked identical before this field existed. No UI
  // consumes this yet; exposing it here first so a future "please log in
  // again" affordance doesn't also need a Rust-side change.
  needs_reauth: boolean;
}

export interface SyncDiffInfo {
  push_new: number;
  pull_new: number;
  push_delete: number;
  pull_delete: number;
  pull_update: number;
  push_recreate: number;
  reachable: boolean;
}

const EMPTY_STATUS: SyncStatusInfo = {
  running: false, server_url: null, vault_path: null, tracked_files: 0, needs_reauth: false,
};
const EMPTY_DIFF: SyncDiffInfo = {
  push_new: 0, pull_new: 0, push_delete: 0, pull_delete: 0,
  pull_update: 0, push_recreate: 0, reachable: false,
};

export async function syncStart(): Promise<void> {
  if (!isTauri) return;
  try { await invoke("sync_start"); } catch { /* already running — fine, status reflects reality */ }
}

export async function syncStop(): Promise<void> {
  if (!isTauri) return;
  try { await invoke("sync_stop"); } catch {}
}

export async function syncEngineStatus(): Promise<SyncStatusInfo> {
  if (!isTauri) return EMPTY_STATUS;
  try { return await invoke<SyncStatusInfo>("sync_engine_status"); } catch { return EMPTY_STATUS; }
}

export async function syncDiff(): Promise<SyncDiffInfo> {
  if (!isTauri) return EMPTY_DIFF;
  try { return await invoke<SyncDiffInfo>("sync_diff"); } catch { return EMPTY_DIFF; }
}

/// "Auto-start unless Local" policy (cservinl, 2026-07-25) — syncing a
/// local-vault mirror against the same machine's own server is pointless.
/// Always stops first (idempotent even if not already running) so
/// switching between two different remote servers doesn't leave the old
/// one's engine running against the new server_url.
export async function applySyncPolicy(serverUrl: string): Promise<void> {
  if (!isTauri) return;
  await syncStop();
  if (!isLoopbackUrl(serverUrl)) {
    await syncStart();
  }
}
