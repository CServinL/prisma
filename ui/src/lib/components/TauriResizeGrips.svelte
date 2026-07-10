<script lang="ts">
  // CSD (client-side decoration) resize grips for the borderless Tauri
  // window. Rendered by the page as a SIBLING of .shell, never nested
  // inside it — .shell carries a `transform` (web-mode display scale),
  // which would make it a new containing block for these position:fixed
  // grips, resolving their top/right/bottom/left:0 against .shell's own
  // (margined, inset) box instead of the real window edges.
  let { isMaximized = $bindable(false) }: { isMaximized?: boolean } = $props();

  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    (async () => {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const win = getCurrentWindow();
      isMaximized = await win.isMaximized();
      win.onResized(async () => { isMaximized = await win.isMaximized(); });
    })();
  }

  async function startResize(direction: string) {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    // @ts-ignore — startResizeDragging exists on the webview window at
    // runtime but isn't in this package version's public type surface.
    getCurrentWindow().startResizeDragging(direction);
  }
</script>

{#if !isMaximized}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-n"  onmousedown={() => startResize("North")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-s"  onmousedown={() => startResize("South")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-w"  onmousedown={() => startResize("West")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-e"  onmousedown={() => startResize("East")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-nw" onmousedown={() => startResize("NorthWest")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-ne" onmousedown={() => startResize("NorthEast")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-sw" onmousedown={() => startResize("SouthWest")}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div role="none" class="rg rg-se" onmousedown={() => startResize("SouthEast")}></div>
{/if}

<style>
  .rg {
    position: fixed;
    z-index: 9999;
  }
  /* Grips sit entirely within the 20px margin — never cross into shell content */
  .rg-n  { top: 0;    left: 20px;  right: 20px; height: 20px; cursor: n-resize; }
  .rg-s  { bottom: 0; left: 20px;  right: 20px; height: 20px; cursor: s-resize; }
  .rg-w  { left: 0;   top: 20px;   bottom: 20px; width: 20px; cursor: w-resize; }
  .rg-e  { right: 0;  top: 20px;   bottom: 20px; width: 20px; cursor: e-resize; }
  .rg-nw { top: 0; left: 0;    width: 20px; height: 20px; cursor: nw-resize; }
  .rg-ne { top: 0; right: 0;   width: 20px; height: 20px; cursor: ne-resize; }
  .rg-sw { bottom: 0; left: 0;  width: 20px; height: 20px; cursor: sw-resize; }
  .rg-se { bottom: 0; right: 0; width: 20px; height: 20px; cursor: se-resize; }
</style>
