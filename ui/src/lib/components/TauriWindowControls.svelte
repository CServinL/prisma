<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  function winMinimize(e: MouseEvent) {
    e.stopPropagation();
    invoke("window_minimize");
  }
  function winMaximize(e: MouseEvent) {
    e.stopPropagation();
    invoke("window_toggle_maximize");
  }
  function winClose(e: MouseEvent) {
    e.stopPropagation();
    invoke("window_close");
  }
</script>

<div class="window-controls">
  <button class="wc-btn" onmousedown={winMinimize} title="Minimize">&#x2212;</button>
  <button class="wc-btn" onmousedown={winMaximize} title="Maximize">&#x25A1;</button>
  <button class="wc-btn wc-close" onmousedown={winClose} title="Close">&#x2715;</button>
</div>

<style>
  .window-controls {
    display: flex;
    align-items: stretch;
    margin-left: 4px;
    height: 100%;
    flex-shrink: 0;
  }

  .wc-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 100%;
    background: none;
    border: none;
    color: #4a6a8a;
    font-size: 14px;
    cursor: pointer;
    line-height: 1;
    padding: 0;
    border-radius: 0;
    transition: background 0.1s, color 0.1s;
  }
  .wc-btn:hover { background: #1a2a3a; color: #c8ddf0; }
  .wc-close:hover { background: #8b1a1a; color: #fff; }
</style>
