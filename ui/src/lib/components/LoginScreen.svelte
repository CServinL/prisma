<script lang="ts">
  import { login } from "../auth";

  let { serverUrl, onLoggedIn }: { serverUrl: string; onLoggedIn: () => void } = $props();

  let password = $state("");
  let error = $state<string | null>(null);
  let submitting = $state(false);

  function autofocus(el: HTMLInputElement) {
    el.focus();
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!password || submitting) return;
    submitting = true;
    error = null;
    try {
      await login(serverUrl, password);
      password = "";
      onLoggedIn();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      submitting = false;
    }
  }
</script>

<div class="login-overlay">
  <form class="login-box" onsubmit={submit}>
    <h1>Prisma</h1>
    <p class="hint">This server requires a password to connect from this network (ADR-011).</p>
    <input
      type="password"
      bind:value={password}
      placeholder="Password"
      use:autofocus
      disabled={submitting}
    />
    {#if error}
      <p class="error">{error}</p>
    {/if}
    <button type="submit" disabled={submitting || !password}>
      {submitting ? "Connecting…" : "Connect"}
    </button>
  </form>
</div>

<style>
  .login-overlay {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0a1420;
    z-index: 10000;
  }
  .login-box {
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: 280px;
    padding: 24px;
    background: #111f2e;
    border: 1px solid #24384a;
    border-radius: 8px;
  }
  h1 {
    margin: 0 0 4px;
    font-size: 20px;
    color: #c8ddf0;
    text-align: center;
  }
  .hint {
    margin: 0 0 8px;
    font-size: 12px;
    color: #6a8aa8;
    text-align: center;
  }
  input {
    padding: 8px 10px;
    background: #0d1926;
    border: 1px solid #24384a;
    border-radius: 4px;
    color: #e0ecf5;
    font-size: 14px;
  }
  input:focus { outline: none; border-color: #4a90d9; }
  button {
    padding: 8px 10px;
    background: #1a5a9a;
    border: none;
    border-radius: 4px;
    color: #fff;
    font-size: 14px;
    cursor: pointer;
  }
  button:disabled { opacity: 0.6; cursor: default; }
  button:not(:disabled):hover { background: #2a6ab0; }
  .error {
    margin: 0;
    font-size: 12px;
    color: #e07a7a;
  }
</style>
