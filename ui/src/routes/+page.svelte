<script lang="ts">
  type NodeType = "note" | "source" | "chat" | "stream";
  type GState = "idle" | "indexing" | "stale";

  interface ServerStatus {
    online: boolean;
    config: { ok: boolean; error: string | null };
    pending_jobs: number;
    graphify: { state: GState; last_indexed: string | null; last_error?: string | null };
    chroma?: { chunks: number; files_indexed: number; model: string } | null;
    vault?: { root: string; notes: number; sources: number; chats: number; streams: number };
    zotero?: { mode: string; available: boolean } | null;
    ollama?: { reachable: boolean } | null;
  }

  interface NodeMeta {
    slug: string;
    title: string;
    node_type: NodeType;
    tags: string[];
    modified_at: string;
    citekey?: string;
    authors?: string[];
    year?: number;
    original_ext?: string;
    // stream extras
    stream_status?: string;
    refresh_frequency?: string;
    total_papers?: number;
    last_updated?: string;
    query?: string;
  }

  interface VaultListing {
    sources: NodeMeta[];
    notes: NodeMeta[];
    chats: NodeMeta[];
    streams: NodeMeta[];
  }

  interface RenderedNode {
    slug: string;
    title: string;
    node_type: NodeType;
    html: string;
    broken_links: string[];
    broken_citations: string[];
    original_ext?: string;
    has_md?: boolean;
    stream_status?: string;
    refresh_frequency?: string;
    total_papers?: number;
    last_updated?: string;
    next_update?: string;
    query?: string;
    collection_key?: string;
  }

  interface SearchResult {
    slug: string;
    title: string;
    excerpt: string;
    score?: number;
  }

  interface DeepSearchResult {
    slug: string;
    title: string;
    excerpt: string;
    score: number;
    reason: string;
  }

  interface VaultTreeNode {
    name: string;
    kind: "dir" | "file";
    children?: VaultTreeNode[];
    slug?: string;
    title?: string;
    node_type?: NodeType;
    modified_at?: string;
    stream_status?: string;
  }

  interface StreamMeta {
    slug: string;
    title: string;
    description?: string;
    query: string;
    status: string;       // "active" | "paused" | "archived"
    refresh_frequency: string;
    total_papers: number;
    last_updated?: string;
    next_update?: string;
    tags: string[];
  }

  const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  if (isTauri) document.documentElement.classList.add("tauri");

  const DEFAULT_API = "http://127.0.0.1:8765";
  // In browser/PWA the UI is served from the same origin as the API — no config needed.
  // In Tauri the server can be at any address, so respect the stored/configured value.
  let apiBase = $state(
    isTauri
      ? (localStorage.getItem("prisma.server") ?? DEFAULT_API)
      : window.location.origin
  );

  let viewFormat = $state<"html" | "md">("html");
  let tree = $state<VaultTreeNode[]>([]);
  let collapsedDirs = $state<Set<string>>(new Set());
  let treeLoaded = $state(false);
  let sidebarEl = $state<HTMLElement | null>(null);
  // context menu
  let ctxMenu = $state<{ x: number; y: number; slug: string | null; title: string; dirKey: string | null } | null>(null);
  let ctxMovePicker = $state(false);
  let renameTarget = $state<{ slug: string; value: string } | null>(null);
  // drag and drop
  let dragSlug = $state<string | null>(null);
  let dragOverKey = $state<string | null>(null);
  let hoverExpandTimer: ReturnType<typeof setTimeout> | null = null;
  let activeNode = $state<RenderedNode | null>(null);
  let serverOnline = $state(false);
  let graphifyState = $state<GState | null>(null);
  let graphifyLastIndexed = $state<string | null>(null);
  let serverStatus = $state<ServerStatus | null>(null);
  let statusPopoverOpen = $state(false);
  let searchQuery = $state("");
  let searchResults = $state<SearchResult[]>([]);
  let searching = $state(false);
  let loadingNode = $state(false);

  let showDeepSearch = $state(false);
  let deepQuery = $state("");
  let deepResults = $state<DeepSearchResult[]>([]);
  let deepSearching = $state(false);
  let deepTimer: ReturnType<typeof setTimeout> | null = null;
  let deepPhase = $state(0);
  let deepPhaseTimer: ReturnType<typeof setInterval> | null = null;
  const DEEP_PHASES = ["Reading graph context…", "Asking Ollama…", "Ranking results…"];

  let streams = $state<StreamMeta[]>([]);
  let chats = $state<NodeMeta[]>([]);
  let sectionOpen = $state<Record<string, boolean>>({ vault: true, streams: true, chats: false, zotero: false });

  interface ZoteroStatus { mode: string; available: boolean; db_path?: string; }
  interface ZoteroCollection { key: string; name: string; parent_key?: string; }
  interface ZoteroItem {
    key: string; title: string; item_type: string;
    authors: string[]; year?: number; abstract?: string;
    doi?: string; url?: string; publication?: string;
    tags: string[]; collection_keys: string[];
  }

  let zoteroStatus = $state<ZoteroStatus | null>(null);
  let zoteroCollections = $state<ZoteroCollection[]>([]);
  let zoteroItems = $state<ZoteroItem[]>([]);
  let zoteroCollection = $state<string | null>(null);
  let zoteroQ = $state("");
  let zoteroSearchTimer: ReturnType<typeof setTimeout> | null = null;
  let importingKey = $state<string | null>(null);
  let zoteroLoading = $state(false);

  function toggleSection(key: string) {
    const opening = !sectionOpen[key];
    sectionOpen = { ...sectionOpen, [key]: opening };
    if (key === "zotero" && opening && zoteroStatus?.available) {
      loadZoteroCollections().then(() => loadZoteroItems());
    }
  }

  // ── Bootstrap ───────────────────────────────────────────────────────────────

  async function bootstrap() {
    serverOnline = await ping();
    if (!serverOnline) return;
    await Promise.all([loadTree(), loadHome(), loadStreams(), loadChats(), loadZoteroStatus()]);
    pollStatus();
  }

  async function ping(): Promise<boolean> {
    try {
      const r = await fetch(`${apiBase}/health`, { signal: AbortSignal.timeout(2000) });
      return r.ok;
    } catch { return false; }
  }

  function initCollapsed(nodes: VaultTreeNode[], prefix = "", out = new Set<string>()) {
    for (const n of nodes) {
      if (n.kind === "dir") {
        const key = `${prefix}/${n.name}`;
        if (prefix !== "") out.add(key); // collapse beyond depth 1
        initCollapsed(n.children ?? [], key, out);
      }
    }
    return out;
  }

  function allDirs(nodes: VaultTreeNode[], prefix = ""): { path: string; label: string; depth: number }[] {
    const out: { path: string; label: string; depth: number }[] = [];
    for (const n of nodes) {
      if (n.kind === "dir") {
        const p = prefix ? `${prefix}/${n.name}` : n.name;
        out.push({ path: p, label: n.name, depth: prefix.split("/").filter(Boolean).length });
        out.push(...allDirs(n.children ?? [], p));
      }
    }
    return out;
  }

  async function loadTree() {
    try {
      const r = await fetch(`${apiBase}/tree`);
      if (r.ok) {
        tree = await r.json();
        if (!treeLoaded) { collapsedDirs = initCollapsed(tree); treeLoaded = true; }
      }
    } catch {}
  }

  async function moveNode(slug: string, destDir: string) {
    ctxMenu = null; ctxMovePicker = false;
    const r = await fetch(`${apiBase}/nodes/${encodeURIComponent(slug)}/move`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dest_dir: destDir }),
    });
    if (r.ok) {
      const { slug: newSlug } = await r.json();
      await loadTree();
      if (activeNode?.slug === slug) await openNode(newSlug);
    }
  }

  async function doRename() {
    if (!renameTarget) return;
    const { slug, value } = renameTarget;
    renameTarget = null;
    const r = await fetch(`${apiBase}/nodes/${encodeURIComponent(slug)}/rename`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: value }),
    });
    if (r.ok) {
      const { slug: newSlug } = await r.json();
      await loadTree();
      if (activeNode?.slug === slug) await openNode(newSlug);
    }
  }

  async function doDelete(slug: string) {
    ctxMenu = null;
    if (!confirm("Delete this item permanently?")) return;
    await fetch(`${apiBase}/nodes/${encodeURIComponent(slug)}`, { method: "DELETE" });
    await loadTree();
    if (activeNode?.slug === slug) activeNode = null;
  }

  async function doCreateDir(parentKey: string) {
    ctxMenu = null;
    const name = prompt("New folder name:");
    if (!name?.trim()) return;
    const rel = (parentKey.startsWith("/") ? parentKey.slice(1) : parentKey) + "/" + name.trim();
    await fetch(`${apiBase}/dirs`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: rel }),
    });
    await loadTree();
  }

  function onDragStart(e: DragEvent, slug: string) {
    dragSlug = slug;
    e.dataTransfer!.effectAllowed = "move";
    e.dataTransfer!.setData("text/plain", slug);
  }

  function onDragEnd() { dragSlug = null; dragOverKey = null; }

  function onDirDragEnter(e: DragEvent, key: string) {
    e.preventDefault();
    dragOverKey = key;
    if (hoverExpandTimer) clearTimeout(hoverExpandTimer);
    if (collapsedDirs.has(key)) {
      hoverExpandTimer = setTimeout(() => {
        const s = new Set(collapsedDirs); s.delete(key); collapsedDirs = s;
      }, 700);
    }
  }

  function onDirDragLeave(e: DragEvent, key: string) {
    if (hoverExpandTimer) { clearTimeout(hoverExpandTimer); hoverExpandTimer = null; }
    if (dragOverKey === key) dragOverKey = null;
  }

  function onDirDrop(e: DragEvent, dirPath: string) {
    e.preventDefault();
    dragOverKey = null;
    const slug = dragSlug ?? e.dataTransfer?.getData("text/plain");
    if (slug) moveNode(slug, dirPath);
    dragSlug = null;
  }

  function onSidebarDragOver(e: DragEvent) {
    if (!sidebarEl || !dragSlug) return;
    const rect = sidebarEl.getBoundingClientRect();
    const ZONE = 50;
    if (e.clientY < rect.top + ZONE) sidebarEl.scrollTop -= 10;
    else if (e.clientY > rect.bottom - ZONE) sidebarEl.scrollTop += 10;
  }

  async function loadStreams() {
    try {
      const r = await fetch(`${apiBase}/streams`);
      if (r.ok) streams = await r.json();
    } catch {}
  }

  async function loadChats() {
    try {
      const r = await fetch(`${apiBase}/notes?node_type=chat`);
      if (r.ok) {
        const listing = await r.json();
        chats = listing.chats ?? [];
      }
    } catch {}
  }

  async function loadZoteroStatus() {
    try {
      const r = await fetch(`${apiBase}/zotero/status`);
      if (r.ok) zoteroStatus = await r.json();
    } catch {}
  }

  async function loadZoteroCollections() {
    zoteroLoading = true;
    try {
      const r = await fetch(`${apiBase}/zotero/collections`);
      if (r.ok) {
        zoteroCollections = await r.json();
        if (zoteroCollection && !zoteroCollections.find(c => c.key === zoteroCollection)) {
          zoteroCollection = null;
        }
      }
    } catch {} finally { zoteroLoading = false; }
  }

  async function loadZoteroItems(collection?: string | null) {
    zoteroLoading = true;
    const params = new URLSearchParams();
    const coll = collection !== undefined ? collection : zoteroCollection;
    if (coll) params.set("collection", coll);
    if (zoteroQ.trim()) params.set("q", zoteroQ.trim());
    try {
      const r = await fetch(`${apiBase}/zotero/items?${params}`);
      if (r.ok) zoteroItems = await r.json();
    } catch {} finally { zoteroLoading = false; }
  }

  function onZoteroSearch() {
    if (zoteroSearchTimer) clearTimeout(zoteroSearchTimer);
    zoteroSearchTimer = setTimeout(loadZoteroItems, 350);
  }

  async function importZoteroItem(key: string) {
    importingKey = key;
    try {
      const r = await fetch(`${apiBase}/zotero/import/${key}`, { method: "POST" });
      if (r.ok) {
        const node = await r.json();
        activeNode = node;
        await Promise.all([loadTree(), loadZoteroItems()]);
      }
    } catch {} finally { importingKey = null; }
  }

  async function loadHome() {
    loadingNode = true;
    try {
      const r = await fetch(`${apiBase}/home`);
      if (r.ok) activeNode = await r.json();
    } catch {} finally { loadingNode = false; }
  }

  // ── Status polling ──────────────────────────────────────────────────────────

  function pollStatus() {
    fetchStatus();
    setInterval(fetchStatus, 30_000);
  }

  async function fetchStatus() {
    const wasOnline = serverOnline;
    try {
      const r = await fetch(`${apiBase}/status`, { signal: AbortSignal.timeout(3000) });
      if (!r.ok) { serverOnline = false; serverStatus = null; return; }
      const s: ServerStatus = await r.json();
      serverOnline = true;
      serverStatus = s;
      graphifyState = s.graphify?.state ?? null;
      graphifyLastIndexed = s.graphify?.last_indexed ?? null;
      if (!wasOnline) {
        await Promise.all([loadTree(), loadHome(), loadStreams(), loadChats(), loadZoteroStatus()]);
      } else {
        await loadTree();
      }
    } catch { serverOnline = false; serverStatus = null; }
  }

  // ── Reload ──────────────────────────────────────────────────────────────────

  let reloading = $state(false);

  async function reloadServer() {
    reloading = true;
    try {
      await fetch(`${apiBase}/reload`, { method: "POST" });
      await Promise.all([loadTree(), loadStreams(), loadChats(), loadZoteroStatus()]);
    } catch {} finally { reloading = false; }
  }

  // ── Navigation ──────────────────────────────────────────────────────────────

  async function openNode(slug: string, fmt?: "html" | "md") {
    loadingNode = true;
    try {
      const f = fmt ?? viewFormat;
      const url = f === "md" ? `${apiBase}/notes/${slug}?format=md` : `${apiBase}/notes/${slug}`;
      const r = await fetch(url);
      if (r.ok) activeNode = await r.json();
    } catch {} finally { loadingNode = false; }
  }

  async function openStream(slug: string) {
    loadingNode = true;
    try {
      const r = await fetch(`${apiBase}/streams/${slug}/view`);
      if (r.ok) {
        activeNode = await r.json();
        if (activeNode?.collection_key) {
          zoteroCollection = activeNode.collection_key;
          if (zoteroStatus?.available) {
            zoteroLoading = true;
            try {
              if (zoteroCollections.length === 0) {
                const rc = await fetch(`${apiBase}/zotero/collections`);
                if (rc.ok) zoteroCollections = await rc.json();
              }
              const params = new URLSearchParams({ collection: activeNode.collection_key });
              const ri = await fetch(`${apiBase}/zotero/items?${params}`);
              if (ri.ok) zoteroItems = await ri.json();
            } finally { zoteroLoading = false; }
            sectionOpen = { ...sectionOpen, zotero: true };
          }
        }
      }
    } catch {} finally { loadingNode = false; }
  }

  let generatingMd = $state(false);

  async function toggleViewFormat() {
    const next = viewFormat === "html" ? "md" : "html";
    if (next === "md" && activeNode?.original_ext === ".html" && !activeNode.has_md) {
      generatingMd = true;
      try {
        await fetch(`${apiBase}/notes/${activeNode.slug}/md`, { method: "POST" });
      } finally {
        generatingMd = false;
      }
    }
    viewFormat = next;
    if (activeNode) await openNode(activeNode.slug);
  }

  function handleContentClick(e: MouseEvent) {
    const a = (e.target as HTMLElement).closest("a");
    if (!a) return;
    const href = a.getAttribute("href") ?? "";
    if (href.startsWith("#note:") || href.startsWith("#source:")) {
      e.preventDefault();
      openNode(href.split(":")[1]);
    } else if (href.startsWith("http://") || href.startsWith("https://")) {
      e.preventDefault();
      shellOpen(href);
    } else if (href && !href.startsWith("#") && !href.startsWith("/")) {
      // Relative paths (e.g. citation keys from Distill templates) have nowhere to go.
      e.preventDefault();
    }
  }

  // ── Search ──────────────────────────────────────────────────────────────────

  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    if (!searchQuery.trim()) { searchResults = []; return; }
    searchTimer = setTimeout(runSearch, 350);
  }

  async function runSearch() {
    searching = true;
    try {
      const r = await fetch(`${apiBase}/search?q=${encodeURIComponent(searchQuery)}`);
      if (r.ok) searchResults = await r.json();
    } catch {} finally { searching = false; }
  }

  function clearSearch() {
    searchQuery = "";
    searchResults = [];
  }

  function onDeepSearchInput() {
    if (deepTimer) clearTimeout(deepTimer);
    if (!deepQuery.trim()) { deepResults = []; return; }
    deepTimer = setTimeout(runDeepSearch, 500);
  }

  async function runDeepSearch() {
    deepSearching = true;
    deepPhase = 0;
    deepPhaseTimer = setInterval(() => {
      deepPhase = (deepPhase + 1) % DEEP_PHASES.length;
    }, 3500);
    try {
      const r = await fetch(`${apiBase}/search/deep?q=${encodeURIComponent(deepQuery)}`);
      if (r.ok) deepResults = await r.json();
    } catch {} finally {
      deepSearching = false;
      if (deepPhaseTimer) { clearInterval(deepPhaseTimer); deepPhaseTimer = null; }
    }
  }

  function openDeepSearch() {
    deepQuery = searchQuery;
    deepResults = [];
    showDeepSearch = true;
    if (deepQuery.trim()) runDeepSearch();
  }

  // ── Settings ─────────────────────────────────────────────────────────────────

  import { invoke } from "@tauri-apps/api/core";

  let isMaximized = $state(false);

  if (isTauri) {
    (async () => {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const win = getCurrentWindow();
      isMaximized = await win.isMaximized();
      win.onResized(async () => { isMaximized = await win.isMaximized(); });
    })();
  }

  async function startResize(direction: string) {
    if (!isTauri) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    // @ts-ignore
    getCurrentWindow().startResizeDragging(direction);
  }

  function winDrag() {
    if (isTauri) invoke("window_start_drag");
  }
  function winMinimize(e: MouseEvent) {
    e.stopPropagation();
    if (isTauri) invoke("window_minimize");
  }
  function winMaximize(e: MouseEvent) {
    e.stopPropagation();
    if (isTauri) invoke("window_toggle_maximize");
  }
  function winClose(e: MouseEvent) {
    e.stopPropagation();
    if (isTauri) invoke("window_close");
  }
  function shellOpen(url: string) {
    if (isTauri) return invoke("open_url", { url });
    window.open(url, "_blank");
  }

  function handleIframeMessage(e: MessageEvent) {
    if (e.data?.type === "open-url" && typeof e.data.url === "string") {
      shellOpen(e.data.url);
    }
  }
  window.addEventListener("message", handleIframeMessage);

  interface AppSettings { scale: number; server_url: string; }

  const SCALE_OPTIONS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];

  let showSettings = $state(false);
  let cfg = $state<AppSettings>({ scale: 1.0, server_url: apiBase });

  async function loadSettings() {
    try {
      if (isTauri) {
        cfg = await invoke<AppSettings>("get_settings");
      } else {
        const stored = localStorage.getItem("prisma-settings");
        if (stored) cfg = JSON.parse(stored);
      }
      apiBase = cfg.server_url || apiBase;
    } catch {}
  }

  async function saveAndApply() {
    cfg.server_url = apiBase;
    try {
      if (isTauri) {
        await invoke("save_settings_cmd", { settings: cfg });
        await invoke("apply_scale", { scale: cfg.scale });
      } else {
        localStorage.setItem("prisma-settings", JSON.stringify(cfg));
        document.documentElement.style.fontSize = `${cfg.scale * 100}%`;
      }
    } catch {}
    showSettings = false;
    bootstrap();
  }

  // ── Stream form ─────────────────────────────────────────────────────────────

  const FREQ_OPTIONS = ["daily", "weekly", "monthly", "manual"];

  let showStreamForm = $state(false);
  let streamForm = $state({ title: "", query: "", description: "", refresh_frequency: "weekly" });
  let streamFormSaving = $state(false);
  let streamFormError = $state("");

  function openNewStreamForm() {
    streamForm = { title: "", query: "", description: "", refresh_frequency: "weekly" };
    streamFormError = "";
    showStreamForm = true;
  }

  async function submitStreamForm() {
    if (!streamForm.title.trim() || !streamForm.query.trim()) {
      streamFormError = "Title and query are required.";
      return;
    }
    streamFormSaving = true;
    streamFormError = "";
    try {
      const r = await fetch(`${apiBase}/streams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(streamForm),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        streamFormError = err.detail ?? `Error ${r.status}`;
        return;
      }
      showStreamForm = false;
      await Promise.all([loadTree(), loadStreams()]);
    } catch (e) {
      streamFormError = String(e);
    } finally {
      streamFormSaving = false;
    }
  }

  async function deleteStream(slug: string) {
    if (!confirm(`Delete stream "${slug}"?`)) return;
    await fetch(`${apiBase}/streams/${slug}`, { method: "DELETE" });
    if (activeNode?.slug === slug) activeNode = null;
    await Promise.all([loadTree(), loadStreams()]);
  }

  async function patchStreamStatus(slug: string, status: string) {
    await fetch(`${apiBase}/streams/${slug}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await Promise.all([loadStreams(), loadTree()]);
    if (activeNode?.slug === slug) await openNode(slug);
  }

  // ── Init ────────────────────────────────────────────────────────────────────

  loadSettings().then(() => bootstrap());
</script>

<div class="shell" class:maximized={isMaximized}>

  {#if isTauri && !isMaximized}
  <!-- Resize grips (CSD — no native decorations) -->
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

  <!-- Titlebar (CSD) -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="titlebar" onmousedown={winDrag}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="drag-area">
      <span class="logo">Prisma</span>
    </div>

    <div class="search-wrap" onmousedown={e => e.stopPropagation()}>
      <input
        class="search-input"
        bind:value={searchQuery}
        placeholder="Search vault…"
        oninput={onSearchInput}
        onkeydown={e => { if (e.key === "Enter") openDeepSearch(); }}
      />
      {#if searchQuery}
        <button class="clear-btn" onclick={clearSearch} title="Clear">✕</button>
      {/if}
      {#if searching}
        <span class="spinner-sm"></span>
      {/if}
      <button class="deep-btn" onclick={openDeepSearch} title="Deep search (graph + semantic)">⌕</button>
    </div>

    <button class="icon-btn" onmousedown={e => e.stopPropagation()} onclick={() => showSettings = !showSettings} title="Settings">⚙</button>

    <!-- Status dot + popover -->
    <div class="status-anchor" onmousedown={e => e.stopPropagation()}>
      <button
        class="gdot-btn"
        class:offline={!serverOnline}
        class:error={serverOnline && !serverStatus?.config?.ok}
        class:indexing={serverOnline && serverStatus?.config?.ok && graphifyState === "indexing"}
        class:stale={serverOnline && serverStatus?.config?.ok && graphifyState === "stale"}
        class:idle={serverOnline && serverStatus?.config?.ok && graphifyState === "idle"}
        onclick={() => statusPopoverOpen = !statusPopoverOpen}
        title="System status"
      ></button>
      {#if statusPopoverOpen}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="status-backdrop" onclick={() => statusPopoverOpen = false}></div>
        <div class="status-popover">
          <div class="sp-header">System status</div>

          <div class="sp-section">
            <span class="sp-label">Server</span>
            <span class="sp-val" class:ok={serverOnline} class:bad={!serverOnline}>
              {serverOnline ? "online" : "offline"}
            </span>
          </div>

          {#if serverStatus}
            <div class="sp-section">
              <span class="sp-label">Config</span>
              <span class="sp-val" class:ok={serverStatus.config.ok} class:bad={!serverStatus.config.ok}>
                {serverStatus.config.ok ? "ok" : serverStatus.config.error ?? "error"}
              </span>
            </div>

            <div class="sp-section">
              <span class="sp-label">Internet</span>
              <span class="sp-val" class:ok={serverStatus.online} class:warn={!serverStatus.online}>
                {serverStatus.online ? "reachable" : "offline"}
              </span>
            </div>

            {#if serverStatus.ollama != null}
              <div class="sp-section">
                <span class="sp-label">Ollama</span>
                <span class="sp-val" class:ok={serverStatus.ollama.reachable} class:bad={!serverStatus.ollama.reachable}>
                  {serverStatus.ollama.reachable ? "reachable" : "offline"}
                </span>
              </div>
            {/if}

            {#if serverStatus.vault}
              <div class="sp-section">
                <span class="sp-label">Vault</span>
                <span class="sp-val ok">
                  {serverStatus.vault.notes}n · {serverStatus.vault.sources}s · {serverStatus.vault.chats}c · {serverStatus.vault.streams}st
                </span>
              </div>
              <div class="sp-vault-root">{serverStatus.vault.root}</div>
            {/if}

            <div class="sp-section">
              <span class="sp-label">Graphify</span>
              <span class="sp-val"
                class:ok={graphifyState === "idle"}
                class:warn={graphifyState === "stale"}
                class:info={graphifyState === "indexing"}
              >
                {graphifyState ?? "—"}
                {#if graphifyLastIndexed && graphifyState === "idle"}
                  · {new Date(graphifyLastIndexed).toLocaleTimeString()}
                {/if}
              </span>
            </div>
            {#if serverStatus.graphify?.last_error}
              <div class="sp-error">{serverStatus.graphify.last_error}</div>
            {/if}

            {#if serverStatus.chroma}
              <div class="sp-section">
                <span class="sp-label">Chroma</span>
                <span class="sp-val" class:ok={serverStatus.chroma.chunks > 0} class:warn={serverStatus.chroma.chunks === 0}>
                  {serverStatus.chroma.chunks} chunks · {serverStatus.chroma.files_indexed} files
                </span>
              </div>
              <div class="sp-vault-root">{serverStatus.chroma.model}</div>
            {/if}

            {#if serverStatus.zotero}
              <div class="sp-section">
                <span class="sp-label">Zotero</span>
                <span class="sp-val"
                  class:ok={serverStatus.zotero.available}
                  class:warn={!serverStatus.zotero.available}
                >
                  {serverStatus.zotero.mode} · {serverStatus.zotero.available ? "available" : "unavailable"}
                </span>
              </div>
            {/if}

            {#if serverStatus.pending_jobs > 0}
              <div class="sp-section">
                <span class="sp-label">Jobs</span>
                <span class="sp-val warn">{serverStatus.pending_jobs} pending</span>
              </div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>

    {#if isTauri}
    <div class="window-controls">
      <button class="wc-btn" onmousedown={winMinimize} title="Minimize">&#x2212;</button>
      <button class="wc-btn" onmousedown={winMaximize} title="Maximize">&#x25A1;</button>
      <button class="wc-btn wc-close" onmousedown={winClose} title="Close">&#x2715;</button>
    </div>
    {/if}
  </div>

  <!-- Workspace -->
  <div class="workspace">

    <!-- Sidebar -->
    <aside class="sidebar">
      {#if !serverOnline}
        <div class="sidebar-offline">
          Server offline<br/>
          <code>prisma serve</code>
        </div>
      {:else if searchQuery.trim() && searchResults.length > 0}
        <div class="section-header">Results</div>
        {#each searchResults as r}
          <button class="result-item" class:active={activeNode?.slug === r.slug} onclick={() => openNode(r.slug)}>
            <span class="result-title">{r.title}</span>
            {#if r.excerpt}<span class="result-excerpt">{r.excerpt}</span>{/if}
          </button>
        {/each}
      {:else if searchQuery.trim() && !searching}
        <div class="sidebar-empty">No results</div>
      {:else}
        {#snippet treeNode(node: VaultTreeNode, path: string)}
          {#if node.kind === "dir"}
            {@const key = path + "/" + node.name}
            {@const dirPath = key.startsWith("/") ? key.slice(1) : key}
            {@const open = !collapsedDirs.has(key)}
            <div class="tree-dir">
              <button
                class="tree-dir-row"
                class:drag-over={dragOverKey === key}
                onclick={() => { const s = new Set(collapsedDirs); open ? s.add(key) : s.delete(key); collapsedDirs = s; }}
                oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, slug: null, title: node.name, dirKey: key }; ctxMovePicker = false; }}
                ondragover={(e) => { e.preventDefault(); e.dataTransfer!.dropEffect = "move"; }}
                ondragenter={(e) => onDirDragEnter(e, key)}
                ondragleave={(e) => onDirDragLeave(e, key)}
                ondrop={(e) => onDirDrop(e, dirPath)}
              >
                <span class="tree-chevron" class:open>{open ? "▾" : "▸"}</span>
                <span class="tree-dir-name">{node.name}</span>
              </button>
              {#if open}
                <div class="tree-children">
                  {#each node.children ?? [] as child}
                    {@render treeNode(child, key)}
                  {/each}
                </div>
              {/if}
            </div>
          {:else}
            <button
              class="tree-file"
              class:active={activeNode?.slug === node.slug}
              draggable="true"
              onclick={() => node.slug && openNode(node.slug)}
              oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, slug: node.slug ?? null, title: node.title ?? node.name, dirKey: null }; ctxMovePicker = false; }}
              ondragstart={(e) => node.slug && onDragStart(e, node.slug)}
              ondragend={onDragEnd}
            >
              <span class="tree-type-dot nt-{node.node_type ?? 'note'}"
                class:sdot-active={node.stream_status === "active"}
                class:sdot-paused={node.stream_status === "paused"}
                class:sdot-archived={node.stream_status === "archived"}
              ></span>
              <span class="tree-file-name">{node.title ?? node.name}</span>
            </button>
          {/if}
        {/snippet}

        <!-- Home -->
        <button class="home-btn" class:active={activeNode?.slug === "home"} onclick={loadHome}>
          Home
        </button>

        <!-- Vault section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("vault")}>
            <span class="section-chevron" class:open={sectionOpen.vault}>{sectionOpen.vault ? "▾" : "▸"}</span>
            <span class="section-label">Vault</span>
          </button>
        </div>
        {#if sectionOpen.vault}
          <div class="section-body section-body-scroll" bind:this={sidebarEl} ondragover={onSidebarDragOver}>
            {#if tree.length > 0}
              {#each tree as node}
                {@render treeNode(node, "")}
              {/each}
            {:else}
              <div class="sidebar-empty">Empty vault</div>
            {/if}
          </div>
        {/if}

        <!-- Streams section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("streams")}>
            <span class="section-chevron" class:open={sectionOpen.streams}>{sectionOpen.streams ? "▾" : "▸"}</span>
            <span class="section-label">Streams</span>
          </button>
          <button class="section-action" onclick={() => openNewStreamForm()}>+</button>
        </div>
        {#if sectionOpen.streams}
          <div class="section-body">
            {#if streams.length > 0}
              {#each streams as s}
                <button
                  class="tree-file"
                  class:active={activeNode?.slug === s.slug}
                  onclick={() => openStream(s.slug)}
                >
                  <span class="tree-type-dot nt-stream sdot-{s.status}"></span>
                  <span class="tree-file-name">{s.title}</span>
                </button>
              {/each}
            {:else}
              <div class="sidebar-empty">No streams — press + to create one</div>
            {/if}
          </div>
        {/if}

        <!-- Chats section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("chats")}>
            <span class="section-chevron" class:open={sectionOpen.chats}>{sectionOpen.chats ? "▾" : "▸"}</span>
            <span class="section-label">Chats</span>
          </button>
        </div>
        {#if sectionOpen.chats}
          <div class="section-body">
            {#if chats.length > 0}
              {#each chats as c}
                <button
                  class="tree-file"
                  class:active={activeNode?.slug === c.slug}
                  onclick={() => openNode(c.slug)}
                >
                  <span class="tree-type-dot nt-chat"></span>
                  <span class="tree-file-name">{c.title}</span>
                </button>
              {/each}
            {:else}
              <div class="sidebar-empty">No chats yet</div>
            {/if}
          </div>
        {/if}

        <!-- Zotero section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("zotero")}>
            <span class="section-chevron" class:open={sectionOpen.zotero}>{sectionOpen.zotero ? "▾" : "▸"}</span>
            <span class="section-label">Zotero</span>
            {#if zoteroStatus}
              <span class="zotero-mode-badge" class:available={zoteroStatus.available}>{zoteroStatus.mode}</span>
            {/if}
          </button>
        </div>
        {#if sectionOpen.zotero}
          <div class="section-body section-body-scroll zotero-panel">
            {#if zoteroLoading}
              <div class="zotero-busy">
                <div class="zotero-busy-spinner"></div>
                <span class="zotero-busy-label">Loading…</span>
              </div>
            {/if}
            {#if !zoteroStatus?.available}
              <div class="sidebar-empty">
                Zotero not available.<br/>
                Set <code>zotero.mode</code> in settings.
              </div>
            {:else}
              {#if zoteroCollections.length > 0}
                <div class="zotero-collections">
                  <button
                    class="zotero-coll-btn"
                    class:active={zoteroCollection === null}
                    onclick={() => { zoteroCollection = null; loadZoteroItems(null); }}
                  >All</button>
                  {#each zoteroCollections as c}
                    <button
                      class="zotero-coll-btn"
                      class:active={zoteroCollection === c.key}
                      onclick={() => { zoteroCollection = c.key; loadZoteroItems(c.key); }}
                    >{c.name}</button>
                  {/each}
                </div>
              {/if}
              <div class="zotero-search-row">
                <input
                  class="zotero-search"
                  bind:value={zoteroQ}
                  placeholder="Filter items…"
                  oninput={onZoteroSearch}
                />
              </div>
              {#if zoteroItems.length === 0}
                <div class="sidebar-empty">No items</div>
              {:else}
                {#each zoteroItems as item}
                  <div class="zotero-item">
                    <div class="zotero-item-title">{item.title}</div>
                    <div class="zotero-item-meta">
                      {item.authors[0] ?? ""}
                      {#if item.authors.length > 1} et al.{/if}
                      {item.year ? ` · ${item.year}` : ""}
                    </div>
                    <div class="zotero-item-actions">
                      <button class="zotero-open-btn" onclick={() => shellOpen(`zotero://select/library/items/${item.key}`)}>Open</button>
                      <button
                        class="zotero-import-btn"
                        disabled={importingKey === item.key}
                        onclick={() => importZoteroItem(item.key)}
                      >{importingKey === item.key ? "Importing…" : "Import"}</button>
                    </div>
                  </div>
                {/each}
              {/if}
            {/if}
          </div>
        {/if}
      {/if}
    </aside>

    <!-- Main -->
    <main class="main">
      {#if !serverOnline}
        <div class="empty-state">
          <p>Prisma server is not running.</p>
          <code>prisma serve</code>
        </div>
      {:else if loadingNode}
        <div class="empty-state"><span class="spinner"></span></div>
      {:else if activeNode}
        <div class="node-toolbar">
          <button
            class="node-type-badge {activeNode.node_type}"
            title="Click to toggle type"
            onclick={async () => {
              if (!activeNode || activeNode.node_type === "stream" || activeNode.node_type === "chat") return;
              const next = activeNode.node_type === "note" ? "source" : "note";
              const r = await fetch(`${apiBase}/notes/${activeNode.slug}/type`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ node_type: next }),
              });
              if (r.ok) {
                activeNode = { ...activeNode, node_type: next as NodeType };
                await loadTree();
              }
            }}
          >{activeNode.node_type}</button>
          <span class="node-heading">{activeNode.title}</span>
          {#if activeNode.node_type === "stream"}
            <span class="stream-dot sdot-{activeNode.stream_status}" title={activeNode.stream_status}></span>
            <span class="stream-stat">{activeNode.total_papers ?? 0} papers</span>
            {#if activeNode.stream_status !== "archived"}
              {#if activeNode.stream_status === "active"}
                <button class="toolbar-btn" onclick={() => patchStreamStatus(activeNode!.slug, "paused")}>Pause</button>
              {:else}
                <button class="toolbar-btn" onclick={() => patchStreamStatus(activeNode!.slug, "active")}>Resume</button>
              {/if}
            {/if}
            <button class="toolbar-btn danger" onclick={() => deleteStream(activeNode!.slug)}>Delete</button>
          {/if}
          {#if activeNode.original_ext === ".html" || activeNode.has_md}
            <button
              class="format-toggle"
              class:active={viewFormat === "md"}
              disabled={generatingMd}
              onclick={toggleViewFormat}
              title={viewFormat === "html" ? "Switch to Markdown view" : "Switch to HTML view"}
            >{generatingMd ? "…" : viewFormat === "html" ? "HTML" : "MD"}</button>
          {/if}
          {#if activeNode.original_ext === ".html"}
            <button class="open-original" onclick={async () => {
              try {
                await shellOpen(`${apiBase}/notes/${activeNode!.slug}/view`);
              } catch(e) {
                alert("Open failed: " + e);
              }
            }}>
              Open HTML
            </button>
          {/if}
          {#if activeNode.broken_links.length}
            <span class="warn-badge" title="Broken links: {activeNode.broken_links.join(', ')}">
              {activeNode.broken_links.length} broken link{activeNode.broken_links.length > 1 ? "s" : ""}
            </span>
          {/if}
        </div>
        {#if activeNode.node_type === "stream" && activeNode.query}
          <div class="stream-info-bar">
            <span class="stream-info-label">Query</span>
            <span class="stream-info-value">{activeNode.query}</span>
            {#if activeNode.refresh_frequency}
              <span class="stream-info-label">Frequency</span>
              <span class="stream-info-value">{activeNode.refresh_frequency}</span>
            {/if}
            {#if activeNode.last_updated}
              <span class="stream-info-label">Last run</span>
              <span class="stream-info-value">{new Date(activeNode.last_updated).toLocaleString()}</span>
            {/if}
            {#if activeNode.next_update}
              <span class="stream-info-label">Next run</span>
              <span class="stream-info-value">{new Date(activeNode.next_update).toLocaleString()}</span>
            {/if}
          </div>
        {/if}
        {#if activeNode.original_ext === ".html"}
          {#key activeNode.slug}
          <iframe
            class="html-frame"
            src="/notes/{activeNode.slug}/view"
            title={activeNode.title}
          ></iframe>
          {/key}
        {:else}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="rendered" onclick={handleContentClick}>
          {@html activeNode.html}
        </div>
        {/if}
      {:else}
        <div class="empty-state">
          <p>Select a note or source from the sidebar.</p>
        </div>
      {/if}
    </main>

  </div>

  <!-- New stream form -->
  {#if showStreamForm}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="settings-backdrop" onclick={() => showStreamForm = false}></div>
  <div class="settings-panel">
    <div class="settings-header">
      <span>New stream</span>
      <button class="icon-btn" onclick={() => showStreamForm = false}>✕</button>
    </div>
    <div class="settings-body">
      <label class="setting-row">
        <span class="setting-label">Title</span>
        <input bind:value={streamForm.title} placeholder="e.g. Mechanistic Interpretability" />
      </label>
      <label class="setting-row">
        <span class="setting-label">Search query</span>
        <input bind:value={streamForm.query} placeholder='e.g. "mechanistic interpretability" circuits' />
        <span class="setting-hint">Used to find papers on arXiv / Semantic Scholar.</span>
      </label>
      <label class="setting-row">
        <span class="setting-label">Description</span>
        <input bind:value={streamForm.description} placeholder="Optional" />
      </label>
      <label class="setting-row">
        <span class="setting-label">Refresh frequency</span>
        <select bind:value={streamForm.refresh_frequency}>
          {#each FREQ_OPTIONS as f}
            <option value={f}>{f.charAt(0).toUpperCase() + f.slice(1)}</option>
          {/each}
        </select>
      </label>
      {#if streamFormError}
        <div class="form-error">{streamFormError}</div>
      {/if}
    </div>
    <div class="settings-footer">
      <button class="btn-primary" onclick={submitStreamForm} disabled={streamFormSaving}>
        {streamFormSaving ? "Creating…" : "Create stream"}
      </button>
      <button class="btn-secondary" onclick={() => showStreamForm = false}>Cancel</button>
    </div>
  </div>
  {/if}

  <!-- Deep search panel -->
  {#if showDeepSearch}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="settings-backdrop" onclick={() => showDeepSearch = false}></div>
  <div class="deep-panel">
    <div class="settings-header">
      <span>Deep search</span>
      <button class="icon-btn" onclick={() => showDeepSearch = false}>✕</button>
    </div>
    <div class="deep-search-bar">
      <input
        class="deep-search-input"
        bind:value={deepQuery}
        placeholder="Search with graph index…"
        oninput={onDeepSearchInput}
        autofocus
      />
      {#if deepSearching}
        <span class="spinner-sm deep-spinner"></span>
      {/if}
    </div>
    <div class="deep-results">
      {#if !deepQuery.trim()}
        <div class="sidebar-empty">Type to search across vault and knowledge graph.</div>
      {:else if deepSearching && deepResults.length === 0}
        <div class="deep-progress">
          <div class="deep-progress-dots">
            <span></span><span></span><span></span>
          </div>
          <div class="deep-progress-phase">{DEEP_PHASES[deepPhase]}</div>
        </div>
      {:else if deepResults.length === 0}
        <div class="sidebar-empty">No results</div>
      {:else}
        {#each deepResults as r}
          <button class="deep-result" onclick={() => { openNode(r.slug); showDeepSearch = false; }}>
            <div class="dr-title">{r.title}</div>
            {#if r.reason}
              <div class="dr-reason">{r.reason}</div>
            {/if}
            {#if r.excerpt}
              <div class="dr-excerpt">{r.excerpt}</div>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
    {#if serverStatus?.graphify && serverStatus.graphify.state !== "idle"}
      <div class="deep-notice">
        {#if serverStatus.graphify.state === "indexing"}
          {#if serverStatus.graphify.last_indexed}
            Re-indexing — results based on previous graph.
          {:else}
            Building graph index for the first time — showing text matches only.
          {/if}
        {:else}
          Graph index stale — showing text matches only.
        {/if}
      </div>
    {/if}
  </div>
  {/if}

  <!-- Settings panel -->
  {#if showSettings}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="settings-backdrop" onclick={() => showSettings = false}></div>
  <div class="settings-panel">
    <div class="settings-header">
      <span>Settings</span>
      <button class="icon-btn" onclick={() => showSettings = false}>✕</button>
    </div>

    <div class="settings-body">
      {#if isTauri}
        <label class="setting-row">
          <span class="setting-label">Display scale</span>
          <select bind:value={cfg.scale}>
            {#each SCALE_OPTIONS as s}
              <option value={s}>{s === 1.0 ? "1× (default)" : `${s}×`}</option>
            {/each}
          </select>
          <span class="setting-hint">Applied immediately — persisted across restarts.</span>
        </label>

        <label class="setting-row">
          <span class="setting-label">Server URL</span>
          <input bind:value={apiBase} placeholder="http://127.0.0.1:8765" />
          <span class="setting-hint">URL of the running <code>prisma serve</code> process.</span>
        </label>
      {/if}

    </div>

    <div class="settings-footer">
      <button class="btn-primary" onclick={saveAndApply}>Save</button>
      <button class="btn-secondary" onclick={() => showSettings = false}>Cancel</button>
    </div>
    <div class="settings-danger-zone">
      <button class="btn-danger" onclick={reloadServer} disabled={reloading}>
        {reloading ? "Reloading…" : "Reload server"}
      </button>
      <span class="setting-hint">Re-reads config.yaml and restarts the indexer.</span>
    </div>
  </div>
  {/if}

  <!-- Context menu -->
  {#if ctxMenu}
    <div class="ctx-overlay" onclick={() => { ctxMenu = null; ctxMovePicker = false; }}></div>
    <div class="ctx-menu" style="left:{ctxMenu.x}px; top:{ctxMenu.y}px">
      {#if !ctxMovePicker}
        {#if ctxMenu.slug}
          <button class="ctx-item" onclick={() => ctxMovePicker = true}>Move to…</button>
          <button class="ctx-item" onclick={() => { renameTarget = { slug: ctxMenu!.slug!, value: ctxMenu!.title }; ctxMenu = null; }}>Rename</button>
          <button class="ctx-item ctx-danger" onclick={() => doDelete(ctxMenu!.slug!)}>Delete</button>
        {/if}
        {#if ctxMenu.dirKey !== null}
          <button class="ctx-item" onclick={() => doCreateDir(ctxMenu!.dirKey!)}>New folder…</button>
        {/if}
      {:else}
        <div class="ctx-picker-label">Move to folder:</div>
        {#each allDirs(tree) as dir}
          <button class="ctx-item ctx-dir-pick" style="padding-left:{8 + dir.depth * 12}px"
            onclick={() => moveNode(ctxMenu!.slug!, dir.path)}>
            {dir.label}
          </button>
        {/each}
      {/if}
    </div>
  {/if}

  <!-- Rename dialog -->
  {#if renameTarget}
    <div class="ctx-overlay" onclick={() => renameTarget = null}></div>
    <div class="rename-dialog">
      <div class="rename-label">Rename</div>
      <input class="rename-input" autofocus bind:value={renameTarget.value}
        onkeydown={(e) => { if (e.key === "Enter") doRename(); if (e.key === "Escape") renameTarget = null; }} />
      <div class="rename-actions">
        <button class="rename-cancel" onclick={() => renameTarget = null}>Cancel</button>
        <button class="rename-ok" onclick={doRename}>Rename</button>
      </div>
    </div>
  {/if}

</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(::-webkit-scrollbar) { width: 12px; height: 12px; }
  :global(::-webkit-scrollbar-track) { background: #0d1525; }
  :global(::-webkit-scrollbar-thumb) { background: #2a4a7a; border-radius: 6px; }
  :global(::-webkit-scrollbar-thumb:hover) { background: #3a6aaa; }
  :global(html, body) {
    height: 100%;
    overflow: hidden;
    background: transparent;
    color: #e8edf8;
    font-family: Inter, "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
  }

  /* ── Shell ──────────────────────────────────────────────────────────────── */
  .shell {
    display: flex;
    flex-direction: column;
    height: 100vh;
    box-sizing: border-box;
    background: #0a0e1a;
  }

  :global(.tauri) .shell {
    margin: 20px;
    height: calc(100vh - 40px);
    border: 2px solid #1e3558;
    border-radius: 6px;
    box-shadow:
      0 0 0 1px rgba(0, 0, 0, 0.5),
      0 0 6px rgba(0, 0, 0, 0.6),
      0 0 14px rgba(0, 0, 0, 0.4),
      0 0 20px rgba(0, 0, 0, 0.2);
    overflow: hidden;
  }

  :global(.tauri) .shell.maximized {
    margin: 0;
    height: 100vh;
    border: none;
    border-radius: 0;
    box-shadow: none;
  }

  /* ── Resize grips (CSD) ────────────────────────────────────────────────── */
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

  /* ── Titlebar (CSD) ────────────────────────────────────────────────────── */
  .titlebar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 0 0 14px;
    background: #080c16;
    border-bottom: 1px solid #1a2d4a;
    flex-shrink: 0;
    height: 38px;
    user-select: none;
  }

  .drag-area {
    display: flex;
    align-items: center;
    padding: 0 8px;
    flex-shrink: 0;
    height: 100%;
    cursor: move;
    min-width: 80px;
  }

  .logo {
    font-size: 14px;
    font-weight: 700;
    color: #4a9eff;
    letter-spacing: 0.06em;
    white-space: nowrap;
    pointer-events: none;
    user-select: none;
  }

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

  .search-wrap {
    flex: 1;
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
  }

  .search-input {
    width: 100%;
    padding: 5px 52px 5px 10px;
    background: #0d1320;
    border: 1px solid #1a2d4a;
    border-radius: 5px;
    color: #e8edf8;
    font-size: 12px;
    font-family: inherit;
    outline: none;
  }
  .search-input:focus { border-color: #4a9eff; }
  .search-input::placeholder { color: #3d5470; }

  .clear-btn {
    position: absolute;
    right: 48px;
    background: none;
    border: none;
    color: #4a6a8a;
    cursor: pointer;
    font-size: 10px;
    padding: 2px 4px;
    line-height: 1;
  }
  .clear-btn:hover { color: #a8c8ff; }

  .spinner-sm {
    position: absolute;
    right: 6px;
    width: 10px; height: 10px;
    border: 1.5px solid #1a3a6a;
    border-top-color: #4a9eff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  /* Status dot + popover */
  .status-anchor {
    position: relative;
    flex-shrink: 0;
    display: flex;
    align-items: center;
  }

  .gdot-btn {
    width: 8px; height: 8px;
    border-radius: 50%;
    border: none;
    padding: 0;
    cursor: pointer;
    flex-shrink: 0;
    background: #3a4a5a;
  }
  .gdot-btn.idle    { background: #22c55e; box-shadow: 0 0 4px #22c55e88; }
  .gdot-btn.stale   { background: #f59e0b; box-shadow: 0 0 4px #f59e0b88; }
  .gdot-btn.error   { background: #f87171; box-shadow: 0 0 4px #f8717188; }
  .gdot-btn.indexing {
    background: #4a9eff;
    box-shadow: 0 0 4px #4a9eff88;
    animation: pulse 1s ease-in-out infinite;
  }
  .gdot-btn.offline { background: #3a4a5a; }

  .status-backdrop {
    position: fixed;
    inset: 0;
    z-index: 19;
  }

  .status-popover {
    position: absolute;
    top: calc(100% + 10px);
    right: 0;
    width: 280px;
    background: #080c16;
    border: 1px solid #1a2d4a;
    border-radius: 6px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    z-index: 20;
    padding: 0;
    overflow: hidden;
  }

  .sp-header {
    padding: 8px 12px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #3d5470;
    border-bottom: 1px solid #0f1a2a;
  }

  .sp-section {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 5px 12px;
  }

  .sp-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #2a4060;
    width: 64px;
    flex-shrink: 0;
  }

  .sp-val {
    font-size: 11px;
    color: #4a6a8a;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sp-val.ok   { color: #22c55e; }
  .sp-val.warn { color: #f59e0b; }
  .sp-val.bad  { color: #f87171; }
  .sp-val.info { color: #4a9eff; }

  .sp-vault-root {
    font-size: 9px;
    color: #1a3050;
    font-family: "JetBrains Mono", monospace;
    padding: 0 12px 5px 88px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .format-toggle {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    padding: 2px 8px;
    background: none;
    border: 1px solid #2a3a5a;
    border-radius: 3px;
    color: #5a7aaa;
    cursor: pointer;
    font-family: inherit;
    flex-shrink: 0;
  }
  .format-toggle:hover { border-color: #4a9eff; color: #4a9eff; }
  .format-toggle.active { border-color: #4a9eff; color: #4a9eff; background: #0d1a2a; }

  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  @keyframes spin  { to { transform: rotate(360deg); } }

  /* ── Workspace ──────────────────────────────────────────────────────────── */
  .workspace { display: flex; flex: 1; overflow: hidden; }

  /* ── Sidebar ────────────────────────────────────────────────────────────── */
  .sidebar {
    width: 220px;
    flex-shrink: 0;
    background: #080c16;
    border-right: 1px solid #1a2d4a;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .home-btn {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 7px 12px;
    background: none;
    border: none;
    border-bottom: 1px solid #0f1a2a;
    color: #4a6a8a;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    flex-shrink: 0;
  }
  .home-btn:hover { color: #c8dff8; background: #0d1829; }
  .home-btn.active { color: #4a9eff; background: #0a1628; }

  .section-header {
    display: flex;
    align-items: center;
    border-top: 1px solid #0f1a2a;
    flex-shrink: 0;
  }
  .section-toggle {
    display: flex;
    align-items: center;
    gap: 5px;
    flex: 1;
    padding: 6px 10px 5px;
    background: none;
    border: none;
    color: #3d5470;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
  }
  .section-toggle:hover { color: #6a9abb; }
  .section-chevron { font-size: 9px; opacity: 0.6; }
  .section-chevron.open { opacity: 1; }
  .section-label { flex: 1; }
  .section-action {
    padding: 1px 8px 1px 6px;
    background: none;
    border: none;
    color: #2a5aaa;
    cursor: pointer;
    font-family: inherit;
    font-size: 14px;
    line-height: 1;
    flex-shrink: 0;
  }
  .section-action:hover { color: #4a9eff; }
  .section-body { padding-bottom: 4px; flex-shrink: 0; }
  .section-body-scroll {
    flex: 1 1 0;
    min-height: 60px;
    max-height: 40vh;
    overflow-y: auto;
    flex-shrink: 1;
  }

  .zotero-panel {
    position: relative;
  }

  .zotero-busy {
    position: absolute;
    inset: 0;
    z-index: 10;
    background: rgba(8, 12, 22, 0.75);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    pointer-events: all;
  }

  .zotero-busy-spinner {
    width: 18px; height: 18px;
    border: 2px solid #1a3a6a;
    border-top-color: #4a9eff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  .zotero-busy-label {
    font-size: 10px;
    color: #4a6a8a;
    letter-spacing: 0.06em;
  }

  .zotero-mode-badge {
    font-size: 9px;
    padding: 1px 4px;
    border-radius: 3px;
    background: #1a2030;
    color: #3d5470;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    margin-left: auto;
    margin-right: 6px;
  }
  .zotero-mode-badge.available { color: #4a9eff; background: #0a1628; }
  .zotero-collections {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 4px 8px;
  }
  .zotero-coll-btn {
    font-size: 10px;
    padding: 2px 6px;
    background: none;
    border: 1px solid #1a3050;
    border-radius: 3px;
    color: #3d5470;
    cursor: pointer;
    font-family: inherit;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 120px;
  }
  .zotero-coll-btn.active, .zotero-coll-btn:hover { color: #4a9eff; border-color: #4a9eff; }
  .zotero-search-row { padding: 4px 8px; }
  .zotero-search {
    width: 100%;
    box-sizing: border-box;
    background: #0a1220;
    border: 1px solid #1a2d4a;
    border-radius: 4px;
    color: #c8dff8;
    font-size: 11px;
    padding: 4px 8px;
    font-family: inherit;
  }
  .zotero-search:focus { outline: none; border-color: #4a9eff; }
  .zotero-item {
    padding: 5px 10px;
    border-bottom: 1px solid #0a1220;
  }
  .zotero-item-title {
    font-size: 11px;
    color: #c8dff8;
    line-height: 1.3;
    margin-bottom: 2px;
  }
  .zotero-item-meta {
    font-size: 10px;
    color: #3d5470;
    margin-bottom: 4px;
  }
  .zotero-item-actions { display: flex; gap: 6px; }
  .zotero-open-btn {
    font-size: 10px;
    padding: 1px 6px;
    background: none;
    border: 1px solid #1a3050;
    border-radius: 3px;
    color: #2a5aaa;
    text-decoration: none;
    cursor: pointer;
  }
  .zotero-open-btn:hover { color: #4a9eff; border-color: #4a9eff; }
  .zotero-import-btn {
    font-size: 10px;
    padding: 1px 6px;
    background: none;
    border: 1px solid #1a3050;
    border-radius: 3px;
    color: #2a5aaa;
    cursor: pointer;
    font-family: inherit;
  }
  .zotero-import-btn:hover:not(:disabled) { color: #4a9eff; border-color: #4a9eff; }
  .zotero-import-btn:disabled { opacity: 0.4; cursor: default; }

  .tree-dir { width: 100%; }

  .tree-dir-row {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    padding: 4px 8px;
    background: none;
    border: none;
    color: #4a6a8a;
    font-size: 11px;
    font-family: inherit;
    text-align: left;
    cursor: pointer;
    user-select: none;
  }
  .tree-dir-row:hover { color: #7a9abb; background: #0a1020; }

  .tree-chevron { font-size: 9px; flex-shrink: 0; color: #2a4060; }
  .tree-chevron.open { color: #4a6a8a; }

  .tree-dir-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }

  .tree-children { padding-left: 10px; }

  .tree-file {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 3px 8px;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    color: #7a9abb;
    font-size: 11px;
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  .tree-file:hover { background: #0d1828; color: #c8ddf0; }
  .tree-file.active { background: #0d1828; color: #c8ddf0; border-left-color: #4a9eff; }

  .tree-file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .tree-type-dot {
    width: 5px; height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
    background: #2a4060;
  }
  .nt-note    { background: #22863a; }
  .nt-source  { background: #2a6eff; }
  .nt-chat    { background: #8b5cf6; }
  .nt-stream  { background: #ca8a04; }
  .sdot-active  { background: #22c55e !important; }
  .sdot-paused  { background: #f59e0b !important; }
  .sdot-archived { background: #3a4a5a !important; }

  .node-excerpt {
    font-size: 10px;
    color: #3d5470;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .result-item {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    padding: 5px 10px;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    cursor: pointer;
    text-align: left;
    gap: 2px;
  }
  .result-item:hover { background: #0d1828; }
  .result-item.active { background: #0d1828; border-left-color: #4a9eff; }

  .result-title {
    font-size: 11px;
    color: #c8ddf0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    width: 100%;
  }

  .result-excerpt {
    font-size: 10px;
    color: #3d5470;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    width: 100%;
  }

  .sidebar-empty {
    padding: 6px 16px 8px;
    font-size: 11px;
    color: #2a4060;
    font-style: italic;
  }

  .stream-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .stream-row {
    display: flex;
    align-items: center;
    gap: 6px;
    overflow: hidden;
  }

  .stream-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
    background: #3a4a5a;
  }
  .stream-dot.sdot-active, .sdot-active   { background: #22c55e; }
  .stream-dot.sdot-paused, .sdot-paused   { background: #f59e0b; }
  .stream-dot.sdot-archived, .sdot-archived { background: #3a4a5a; }

  .stream-meta {
    display: flex;
    gap: 4px;
    font-size: 10px;
    color: #3d5470;
    padding-left: 12px;
  }

  .stream-stat {
    font-size: 11px;
    color: #4a6a8a;
  }

  .stream-info-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 16px;
    padding: 6px 18px;
    background: #080f1e;
    border-bottom: 1px solid #1a2d4a;
    font-size: 11px;
    flex-shrink: 0;
  }
  .stream-info-label {
    color: #3d5470;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 9px;
    letter-spacing: 0.06em;
  }
  .stream-info-value { color: #7a9abb; }

  .toolbar-btn {
    font-size: 10px;
    padding: 2px 8px;
    background: #0d1828;
    border: 1px solid #1a3050;
    border-radius: 3px;
    color: #7a9abb;
    cursor: pointer;
    font-family: inherit;
    flex-shrink: 0;
  }
  .toolbar-btn:hover { border-color: #4a9eff; color: #a8c8ff; }
  .toolbar-btn.danger { border-color: #3a1010; color: #f87171; }
  .toolbar-btn.danger:hover { background: #1a0808; border-color: #f87171; }

  .new-stream-btn {
    width: 100%;
    padding: 6px 16px;
    background: none;
    border: none;
    border-top: 1px solid #0f1a2a;
    color: #2a5aaa;
    font-size: 11px;
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  .new-stream-btn:hover { color: #4a9eff; background: #0d1828; }

  .form-error {
    font-size: 11px;
    color: #f87171;
    background: #1a0808;
    border: 1px solid #3a1010;
    border-radius: 4px;
    padding: 6px 10px;
  }

  .sidebar-offline {
    padding: 20px 14px;
    font-size: 11px;
    color: #4a6a8a;
    line-height: 1.6;
    text-align: center;
  }
  .sidebar-offline code {
    display: block;
    margin-top: 6px;
    font-size: 10px;
    color: #4a9eff;
    font-family: "JetBrains Mono", monospace;
  }

  /* ── Main ───────────────────────────────────────────────────────────────── */
  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #0a0e1a;
  }

  .node-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 18px;
    background: #080c16;
    border-bottom: 1px solid #1a2d4a;
    flex-shrink: 0;
    min-height: 34px;
  }

  .node-type-badge {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 3px;
    flex-shrink: 0;
    cursor: pointer;
    background: none;
    font-family: inherit;
  }
  .node-type-badge.note   { background: #0d2a0d; color: #4ade80; border: 1px solid #1a4a1a; }
  .node-type-badge.source { background: #0d1a2a; color: #4a9eff; border: 1px solid #1a3050; }
  .node-type-badge.chat   { background: #1a0d2a; color: #c084fc; border: 1px solid #2a1a4a; }
  .node-type-badge.stream { background: #1a1a0d; color: #facc15; border: 1px solid #3a3010; }

  .node-heading {
    font-size: 13px;
    font-weight: 500;
    color: #c8ddf0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .html-frame {
    flex: 1;
    width: 100%;
    border: none;
    background: white;
  }

  .open-original {
    font-size: 10px;
    color: #4a9eff;
    background: transparent;
    cursor: pointer;
    padding: 2px 7px;
    border: 1px solid #1a3050;
    border-radius: 3px;
    flex-shrink: 0;
  }
  .open-original:hover { background: #0d1828; }

  .warn-badge {
    font-size: 10px;
    color: #f59e0b;
    background: #1a1000;
    border: 1px solid #3a2800;
    border-radius: 3px;
    padding: 2px 6px;
    flex-shrink: 0;
    cursor: default;
  }

  .rendered {
    flex: 1;
    overflow-y: auto;
    padding: 28px 36px;
  }

  /* Pass-through styles for docu-craft rendered HTML */
  .rendered :global(h1) { font-size: 22px; font-weight: 600; color: #e8edf8; margin-bottom: 16px; }
  .rendered :global(h2) { font-size: 17px; font-weight: 600; color: #c8ddf0; margin: 24px 0 10px; }
  .rendered :global(h3) { font-size: 14px; font-weight: 600; color: #a8c8e0; margin: 18px 0 8px; }
  .rendered :global(p)  { color: #9ab4c8; line-height: 1.7; margin-bottom: 12px; }
  .rendered :global(a)  { color: #4a9eff; text-decoration: none; }
  .rendered :global(a:hover) { text-decoration: underline; }
  .rendered :global(a.wikilink)   { color: #4a9eff; border-bottom: 1px dotted #2a5aaa; }
  .rendered :global(a.citation)   { color: #c084fc; border-bottom: 1px dotted #6a3a9a; }
  .rendered :global(span.broken-wikilink)  { color: #f87171; font-size: 11px; }
  .rendered :global(span.broken-citation) { color: #f87171; font-size: 11px; }
  .rendered :global(.transclusion) {
    border-left: 2px solid #1a3050;
    padding-left: 14px;
    margin: 12px 0;
    opacity: 0.85;
  }
  .rendered :global(code) {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    background: #0d1829;
    color: #82bfff;
    padding: 1px 5px;
    border-radius: 3px;
  }
  .rendered :global(pre) {
    background: #080f1e;
    border: 1px solid #1a2d4a;
    border-radius: 6px;
    padding: 14px;
    overflow-x: auto;
    margin: 12px 0;
  }
  .rendered :global(pre code) { background: none; padding: 0; }
  .rendered :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
    font-size: 12px;
  }
  .rendered :global(th) {
    background: #080f1e;
    color: #7ab4f5;
    padding: 7px 12px;
    border: 1px solid #1a2d4a;
    text-align: left;
  }
  .rendered :global(td) {
    padding: 6px 12px;
    border: 1px solid #1a2d4a;
    color: #8aaabb;
  }
  .rendered :global(tr:hover td) { background: #0d1828; }
  .rendered :global(ul), .rendered :global(ol) {
    padding-left: 20px;
    margin-bottom: 12px;
    color: #9ab4c8;
    line-height: 1.7;
  }
  .rendered :global(blockquote) {
    border-left: 3px solid #1a3050;
    padding-left: 14px;
    color: #6a8aa0;
    margin: 12px 0;
    font-style: italic;
  }
  .rendered :global(hr) { border: none; border-top: 1px solid #1a2d4a; margin: 20px 0; }

  .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #2a4060;
    gap: 10px;
  }
  .empty-state code {
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    color: #4a9eff;
    background: #080f1e;
    padding: 4px 10px;
    border-radius: 4px;
  }

  .spinner {
    width: 20px; height: 20px;
    border: 2px solid #1a3a6a;
    border-top-color: #4a9eff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  /* ── Settings ───────────────────────────────────────────────────────────── */
  .icon-btn {
    background: none;
    border: none;
    color: #4a6a8a;
    cursor: pointer;
    font-size: 14px;
    padding: 3px 5px;
    border-radius: 4px;
    line-height: 1;
    flex-shrink: 0;
  }
  .icon-btn:hover { color: #a8c8ff; background: #0d1828; }

  .settings-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.4);
    z-index: 10;
  }

  :global(.tauri) .settings-backdrop {
    inset: 20px;
    border-radius: 6px;
  }

  .settings-panel {
    position: fixed;
    top: 0; right: 0;
    width: 360px;
    height: 100vh;
    background: #080c16;
    border-left: 1px solid #1a2d4a;
    z-index: 11;
    display: flex;
    flex-direction: column;
    box-shadow: -4px 0 24px rgba(0,0,0,0.5);
  }

  :global(.tauri) .settings-panel {
    top: 22px;
    right: 22px;
    height: calc(100vh - 44px);
    border-radius: 0 4px 4px 0;
    clip-path: inset(0 0 0 -30px round 0 4px 4px 0);
  }

  .settings-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    border-bottom: 1px solid #1a2d4a;
    font-size: 13px;
    font-weight: 600;
    color: #c8ddf0;
    flex-shrink: 0;
  }

  .settings-body {
    flex: 1;
    overflow-y: auto;
    padding: 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .setting-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .setting-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #4a6a8a;
  }

  .setting-row select,
  .setting-row input {
    width: 100%;
    padding: 7px 10px;
    background: #0d1320;
    border: 1px solid #1a2d4a;
    border-radius: 5px;
    color: #e8edf8;
    font-size: 12px;
    font-family: inherit;
    outline: none;
  }
  .setting-row select {
    appearance: none;
    -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%234a6a8a'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 10px center;
    padding-right: 28px;
    cursor: pointer;
  }
  .setting-row select option {
    background: #0d1320;
    color: #e8edf8;
  }
  .setting-row select:focus,
  .setting-row input:focus { border-color: #4a9eff; }

  .setting-hint {
    font-size: 10px;
    color: #2a4060;
    line-height: 1.5;
  }
  .setting-hint code {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    color: #4a9eff;
    background: #080f1e;
    padding: 0 3px;
    border-radius: 2px;
  }

  .settings-footer {
    display: flex;
    gap: 8px;
    padding: 14px 16px;
    border-top: 1px solid #1a2d4a;
    flex-shrink: 0;
  }

  .btn-primary {
    flex: 1;
    padding: 8px;
    background: #1a3a6a;
    border: 1px solid #2a5aaa;
    border-radius: 5px;
    color: #a8c8ff;
    font-size: 12px;
    font-family: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .btn-primary:hover { background: #234a8a; border-color: #4a9eff; color: #fff; }

  .btn-secondary {
    padding: 8px 16px;
    background: none;
    border: 1px solid #1a2d4a;
    border-radius: 5px;
    color: #4a6a8a;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
  }
  .btn-secondary:hover { border-color: #2a4060; color: #7a9abb; }

  .settings-danger-zone {
    border-top: 1px solid #1a2d4a;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .btn-danger {
    align-self: flex-start;
    padding: 6px 14px;
    background: none;
    border: 1px solid #4a1a1a;
    border-radius: 4px;
    color: #8a3030;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
  }
  .btn-danger:hover:not(:disabled) { border-color: #aa3030; color: #cc4444; }
  .btn-danger:disabled { opacity: 0.4; cursor: default; }

  /* ── Deep search ─────────────────────────────────────────────────────────── */
  .deep-btn {
    position: absolute;
    right: 28px;
    background: none;
    border: none;
    color: #2a5aaa;
    cursor: pointer;
    font-size: 13px;
    padding: 1px 3px;
    line-height: 1;
  }
  .deep-btn:hover { color: #4a9eff; }

  .deep-panel {
    position: fixed;
    top: 0; right: 0;
    width: 480px;
    height: 100vh;
    background: #080c16;
    border-left: 1px solid #1a2d4a;
    z-index: 11;
    display: flex;
    flex-direction: column;
    box-shadow: -4px 0 24px rgba(0,0,0,0.5);
  }

  :global(.tauri) .deep-panel {
    top: 22px;
    right: 22px;
    height: calc(100vh - 44px);
    border-radius: 0 4px 4px 0;
    clip-path: inset(0 0 0 -30px round 0 4px 4px 0);
  }

  .deep-search-bar {
    position: relative;
    padding: 12px 16px;
    border-bottom: 1px solid #1a2d4a;
    flex-shrink: 0;
  }

  .deep-search-input {
    width: 100%;
    padding: 8px 32px 8px 12px;
    background: #0d1320;
    border: 1px solid #1a2d4a;
    border-radius: 5px;
    color: #e8edf8;
    font-size: 13px;
    font-family: inherit;
    outline: none;
  }
  .deep-search-input:focus { border-color: #4a9eff; }

  .deep-spinner {
    position: absolute;
    right: 28px;
    top: 50%;
    transform: translateY(-50%);
  }

  .deep-results {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .deep-result {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
    padding: 10px 16px;
    background: none;
    border: none;
    border-bottom: 1px solid #0a1220;
    text-align: left;
    cursor: pointer;
    font-family: inherit;
  }
  .deep-result:hover { background: #0d1828; }

  .dr-title {
    font-size: 13px;
    color: #c8ddf0;
    font-weight: 500;
  }

  .dr-reason {
    font-size: 11px;
    color: #4a7aaa;
    font-style: italic;
    line-height: 1.4;
  }

  .dr-excerpt {
    font-size: 11px;
    color: #4a6a7a;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .deep-progress {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    padding: 48px 16px;
  }

  .deep-progress-dots {
    display: flex;
    gap: 7px;
  }

  .deep-progress-dots span {
    width: 7px;
    height: 7px;
    background: #2a5aaa;
    border-radius: 50%;
    animation: dp-bounce 1.4s ease-in-out infinite;
  }

  .deep-progress-dots span:nth-child(2) { animation-delay: 0.22s; }
  .deep-progress-dots span:nth-child(3) { animation-delay: 0.44s; }

  @keyframes dp-bounce {
    0%, 80%, 100% { transform: scale(0.55); opacity: 0.25; }
    40%           { transform: scale(1);    opacity: 1;    }
  }

  .deep-progress-phase {
    font-size: 11px;
    color: #4a6a8a;
    font-style: italic;
    transition: opacity 0.4s;
  }

  .deep-notice {
    padding: 8px 14px;
    font-size: 10px;
    color: #f59e0b;
    background: #0f1200;
    border-top: 1px solid #1a2000;
    flex-shrink: 0;
  }

  .sp-error {
    font-size: 10px;
    color: #f87171;
    padding: 2px 12px 5px 88px;
    line-height: 1.4;
    word-break: break-word;
  }

  /* drag-and-drop */
  .tree-file[draggable="true"] { cursor: grab; }
  .tree-file[draggable="true"]:active { cursor: grabbing; }
  .tree-dir-row.drag-over { background: #0a2040; outline: 1px solid #2a6aaa; }

  /* context menu */
  .ctx-overlay {
    position: fixed; inset: 0; z-index: 900;
  }
  .ctx-menu {
    position: fixed; z-index: 901;
    background: #0d1a2e; border: 1px solid #1a3050;
    border-radius: 6px; padding: 4px 0;
    min-width: 140px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    display: flex; flex-direction: column;
  }
  .ctx-item {
    background: none; border: none; color: #8ab0d0;
    text-align: left; padding: 6px 14px;
    font-size: 12px; cursor: pointer; white-space: nowrap;
  }
  .ctx-item:hover { background: #0a2040; color: #c0d8f0; }
  .ctx-danger { color: #f87171; }
  .ctx-danger:hover { background: #2a0a0a; color: #f87171; }
  .ctx-picker-label { color: #3d5470; font-size: 10px; padding: 4px 14px 2px; }
  .ctx-dir-pick { font-size: 11px; }

  /* rename dialog */
  .rename-dialog {
    position: fixed; z-index: 901;
    top: 50%; left: 50%; transform: translate(-50%, -50%);
    background: #0d1a2e; border: 1px solid #1a3050;
    border-radius: 8px; padding: 16px;
    min-width: 280px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    display: flex; flex-direction: column; gap: 10px;
  }
  .rename-label { color: #8ab0d0; font-size: 12px; }
  .rename-input {
    background: #080f1c; border: 1px solid #1a3050;
    color: #c0d8f0; padding: 6px 10px; border-radius: 4px;
    font-size: 13px; outline: none;
  }
  .rename-input:focus { border-color: #2a6aaa; }
  .rename-actions { display: flex; gap: 8px; justify-content: flex-end; }
  .rename-cancel { background: none; border: 1px solid #1a3050; color: #3d5470; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .rename-ok { background: #1a3a6a; border: none; color: #8ab0d0; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .rename-ok:hover { background: #2a5a9a; }
</style>
