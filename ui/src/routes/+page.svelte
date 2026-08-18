<script lang="ts">
  import { isTauri, DEFAULT_SCALE, applyScale, loadSettings as loadPlatformSettings, saveSettings as savePlatformSettings, shellOpen, pickVaultFolder, apiUrl, type AppSettings } from "$lib/platform";
  import { apiFetch, restoreSession, setAuthRequiredHandler, getToken } from "$lib/auth";
  import { applySyncPolicy, syncEngineStatus, syncDiff, syncStart, syncStop, type SyncStatusInfo, type SyncDiffInfo } from "$lib/sync";
  import LoginScreen from "$lib/components/LoginScreen.svelte";

  type NodeType = "note" | "source" | "chat" | "stream";
  type GState = "idle" | "indexing" | "stale";

  interface ServerStatus {
    online: boolean;
    config: { ok: boolean; error: string | null };
    pending_jobs: number;
    knowledge_graph: {
      state: GState; last_indexed: string | null; last_error?: string | null; current_activity?: string | null;
      sync_total?: number; sync_done?: number;
      current_file?: string | null; current_file_chunks_done?: number; current_file_chunks_total?: number;
      chunk_avg_duration_ms?: number | null; chunk_duration_samples?: number;
      chunk_avg_retries?: number | null;
      chunk_avg_size_tokens?: number | null;
      dropped_chunks_total?: number;
      dropped_chunks_recent?: { source_file: string; error: string; retries: number; reason: string; time: string; dead_letter_path: string | null }[];
    };
    chroma?: { chunks: number; files_indexed: number; model: string; provider?: string; current_activity?: string | null } | null;
    vault?: { root: string; notes: number; sources: number; chats: number; streams: number };
    zotero?: { mode: string; available: boolean; reachable?: boolean } | null;
    // Absent for a cloud chat provider (openrouter/anthropic) -- there's
    // no single "is it up" host to probe for those.
    llm_backend?: { provider: string; reachable: boolean } | null;
    processes?: {
      [worker: string]: { pid: number | null; alive: boolean; restart_count: number; memory_mb: number | null };
    } & {
      system?: { cpu_count: number | null; memory_total_mb: number | null; memory_available_mb: number | null };
    };
    resources?: {
      [pool: string]: {
        type: "gpu" | "cloud";
        capacity: number;
        in_use: number;
        active_model: string | null;
        resident_models: string[];
        vram_budget_mb: number | null;
        models: string[];
        model_capacity: { [model: string]: { in_use: number; limit: number; background_limit: number | null } };
        stats: { granted: number; denied_capacity: number; denied_model_busy: number; denied_vram_budget: number };
        leases: { request_id: string; holder: string; pid: number; model: string | null; held_for_s: number; timeout: number | null; priority: string }[];
      };
    };
    chat_config?: { provider: string; model: string; pool: string };
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

  interface ToolCallOut {
    id: string;
    tool: string;
    args: Record<string, unknown>;
    result: string | null;
    status: "ok" | "error";
  }

  // ADR-019: a turn's claims are one of two node kinds -- CitedClaimNode
  // (traceable to vault sources, `relation` meaningful) or InferenceNode
  // (the model's own reasoning, structurally no sources) -- discriminated
  // on `kind`, matching prisma.storage.models.vault_models.ClaimNode.
  // Rendered as an inline [^N] marker in the turn's content plus a list at
  // the end of the turn — see renderContentSegments() below.
  type ClaimRelation = "citation" | "attribution" | "relational";

  // v3 (schema-only until the chat-schema-v3 branch): Toulmin argumentation
  // extension. qualifier/warrant/rebuts exist on both claim kinds but
  // nothing populates them yet -- same "renders if present" posture as
  // `thoughts` below.
  type Qualifier = "certain" | "probable" | "possible" | "tentative";

  interface WarrantOut {
    id: string;
    text: string;
    backing: string[];
  }

  interface CitedClaimOut {
    kind: "claim";
    index: number;
    claim_text: string;
    sources: string[];
    relation: ClaimRelation;
    faithfulness_checked: boolean | null;
    qualifier: Qualifier | null;
    warrant: WarrantOut | null;
    rebuts: string | null;
  }

  interface InferenceClaimOut {
    kind: "inference";
    index: number;
    claim_text: string;
    qualifier: Qualifier | null;
    warrant: WarrantOut | null;
    rebuts: string | null;
  }

  type ClaimOut = CitedClaimOut | InferenceClaimOut;

  // v3: a media artifact, either the assistant's own output (`media`,
  // PRODUCES) or something a human turn attached as input (`attachments`,
  // ATTACHES). Two shapes, not four-per-format -- see
  // docs/concepts/chat-session-graph.md's Media nodes section.
  interface InlineMediaOut {
    id: string;
    kind: "svg" | "latex" | "drawio";
    value: string;
    caption: string | null;
  }

  interface AssetMediaOut {
    id: string;
    kind: "jpg" | "pdf";
    asset_path: string;
    caption: string | null;
  }

  type MediaOut = InlineMediaOut | AssetMediaOut;

  // ADR-019: schema support only today -- nothing populates a turn's
  // `thoughts` yet (gated behind the still-deferred `has_native_reasoning`
  // model-category flag), but the shape is here so rendering doesn't need
  // to change again once something does.
  interface ThoughtOut {
    id: string;
    thought: string;
    thought_number: number;
    revises: string | null;
    branches_from: string | null;
  }

  // ADR-019: a RECALL hit -- a pointer to another node elsewhere in a
  // session graph that this turn's context assembly pulled in beyond the
  // default rolling history. Never a duplicate of that node's content.
  // chat_slug is null for a same-chat recall, set to the source chat's slug
  // for a cross-chat one (node_id alone is only unique within one chat).
  interface RecallRefOut {
    node_id: string;
    node_kind: string;
    chat_slug: string | null;
  }

  // ADR-019: chat message content is a typed, format-tagged wrapper
  // (schema_gov.RichContent) rather than a flat string -- `format` is
  // always "md" today (svg/latex are schema-forward-compatible, not
  // rendered anywhere yet); `rendered_html` is server-sanitized markdown
  // HTML, computed but deliberately unused for chat turns here (see
  // renderContentSegments below) -- model-generated text stays untrusted,
  // rendered as plain escaped segments client-side, same as before ADR-019.
  interface RichContent {
    format: "md" | "html" | "svg" | "latex";
    value: string;
    rendered_html: string | null;
  }

  interface ChatTurn {
    id?: string;
    role: "user" | "assistant";
    content: RichContent;
    timestamp: string;
    claims: ClaimOut[];
    thoughts: ThoughtOut[];
    tool_calls: ToolCallOut[];
    recalls: RecallRefOut[];
    model?: string | null;
    alternates?: ChatTurn[];
    media?: MediaOut[];          // v3, assistant output
    attachments?: MediaOut[];    // v3, human input
    attached_slugs?: string[];   // v3, human input (vault node references)
  }

  interface ChatDetail {
    slug: string;
    title: string;
    messages: ChatTurn[];
    model: string;
    pinned_turns: number[];
    excerpt_slug: string | null;
    context_tokens_used: number;
    context_tokens_max: number;
    excerpt_regenerating: boolean;
    excerpt_summary_html: string | null;
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

  if (isTauri) document.documentElement.classList.add("tauri");

  const DEFAULT_API = "http://127.0.0.1:8765";
  const DEFAULT_API_PORT = 8765;
  const DEFAULT_WEB_PORT = 8766;
  const DEFAULT_SUPERVISOR_PORT = 8760;

  // serverStatus.llm_backend.provider values -> display label (see app.py's
  // /status: only ever "ollama" or "llama_cpp", the two local providers it
  // probes for reachability).
  const LLM_BACKEND_LABELS: Record<string, string> = { ollama: "Ollama", llama_cpp: "llama.cpp" };

  // The Web process (serving this page at /app) and the API process are
  // independent processes/ports (see ADR-012) — the page's own origin is no
  // longer the same as the API's origin, even in browser/PWA mode.
  const webBase = typeof window !== "undefined" ? window.location.origin : "";

  function formatTokenCount(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + "k";
    return String(n);
  }

  // ADR-017: split a turn's raw content (containing literal "[^1]", "[^2]"
  // markers ChatAgent left in place) into plain-text and marker segments,
  // for the template to render as text / <sup> respectively. Deliberately
  // NOT using {@html} on model-generated text — this codebase treats tool
  // results as untrusted (services/injection_defense.py); the model's own
  // final reply gets the same caution, so segments stay plain strings
  // Svelte auto-escapes rather than becoming raw HTML.
  type ContentSegment = { text: string } | { claimIndex: number };

  const FOOTNOTE_MARKER_RE = /\[\^(\d+)\]/g;

  function renderContentSegments(content: string): ContentSegment[] {
    const segments: ContentSegment[] = [];
    let lastEnd = 0;
    for (const m of content.matchAll(FOOTNOTE_MARKER_RE)) {
      if (m.index! > lastEnd) segments.push({ text: content.slice(lastEnd, m.index) });
      segments.push({ claimIndex: Number(m[1]) });
      lastEnd = m.index! + m[0].length;
    }
    if (lastEnd < content.length) segments.push({ text: content.slice(lastEnd) });
    return segments;
  }

  const CLAIM_RELATION_LABEL: Record<ClaimRelation, string> = {
    citation: "citation",
    attribution: "attribution",
    relational: "relational",
  };

  // Shared between the inline [^N] marker and the claim-list entry below --
  // both key off this rather than raw `relation`/`kind` so the CSS classes
  // (claim-ref-*, claim-relation-*) stay a single flat namespace covering
  // both CitedClaimNode's three relations and InferenceNode.
  function claimStyleKey(c: ClaimOut): string {
    return c.kind === "inference" ? "inference" : c.relation;
  }

  function claimLabel(c: ClaimOut): string {
    return c.kind === "inference" ? "AI inference" : CLAIM_RELATION_LABEL[c.relation];
  }

  // Collapsed-by-default toggle line summarizing a turn's process
  // "spin-offs" -- tool calls, reasoning, recalls -- so the reply itself
  // isn't buried under mechanism by default, while still one click away.
  function summarizeTurnDetails(msg: ChatTurn): string {
    const parts: string[] = [];
    if (msg.tool_calls?.length) parts.push(`${msg.tool_calls.length} tool call${msg.tool_calls.length > 1 ? "s" : ""}`);
    if (msg.thoughts?.length) parts.push(`${msg.thoughts.length} thought${msg.thoughts.length > 1 ? "s" : ""}`);
    if (msg.recalls?.length) parts.push(`${msg.recalls.length} recall${msg.recalls.length > 1 ? "s" : ""}`);
    return parts.join(" · ");
  }

  function _defaultApiBase(): string {
    if (typeof window === "undefined") return DEFAULT_API;
    const url = new URL(window.location.origin);
    url.port = String(DEFAULT_API_PORT);
    return url.origin;
  }

  // Real persisted value arrives async via loadSettings() -> apiUrl(cfg)
  // (platform.ts's own loadSettings: Tauri reads settings.json via the Rust
  // side, browser/PWA reads a "prisma-settings" localStorage key) -- this
  // is just the synchronous placeholder $state needs at declaration time.
  // Previously read a "prisma.server" localStorage key directly here, but
  // nothing ever wrote that specific key in either mode (dead code left
  // over from before the Settings/saved_servers redesign) -- removed
  // rather than fixed, since loadSettings() below is the real source of
  // truth for both modes.
  let apiBase = $state(isTauri ? DEFAULT_API : _defaultApiBase());

  // ── Auth (ADR-011 password mode) ──────────────────────────────────────────
  // Shown whenever apiFetch (or the /ws connection below) hits a 401 —
  // i.e. this server is in the LAN zone with server.auth.mode: password
  // and we don't hold a valid session yet.
  let showLoginScreen = $state(false);
  setAuthRequiredHandler(() => { showLoginScreen = true; });
  // Tauri only: picks up a session already stored in auth.json from a
  // previous run so a restart doesn't force a re-login every time. Reruns
  // whenever apiBase changes too (e.g. the user points Settings at a
  // different server) so that server's own stored session gets checked.
  $effect(() => { restoreSession(apiBase); });
  // Vault-sync: auto-start unless apiBase is Local (syncing a local vault
  // mirror against the same machine is pointless) — reruns on every
  // apiBase change (initial load AND switching servers in Settings), so
  // this one effect is the single place that policy lives.
  $effect(() => { applySyncPolicy(apiBase).then(r => syncBlockedReason = r); });

  // ── WebSocket — API-process push events (vault_change, stream_progress) ──────
  // Hot-reload is handled separately below, by polling the Web process directly —
  // it's a dev-only, self-contained concern local to that process (see ADR-012),
  // not a production event this channel needs to carry.
  let _wsConnected = false;

  function connectWS() {
    const wsBase = apiBase.replace(/^http/, "ws");
    // Same subprotocol scheme as prisma-desktop's own pull.rs — the
    // browser WebSocket API can't set an Authorization header, only
    // subprotocols. Connecting with no token when auth is required just
    // fails and falls into the existing reconnect-with-backoff below,
    // which naturally retries once a token exists post-login.
    const token = getToken();
    const ws = token ? new WebSocket(`${wsBase}/ws`, ["bearer", token]) : new WebSocket(`${wsBase}/ws`);

    ws.onopen = () => { _wsConnected = true; };

    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === "vault_change") {
          loadTree();
        } else if (ev.type === "stream_progress") {
          if (ev.status === "done") loadStreams();
        }
      } catch {}
    };

    ws.onclose = () => {
      _wsConnected = false;
      // Reconnect with backoff — cap at 30 s
      const delay = Math.min(1000 * 2 ** Math.min(_wsRetry, 4), 30000);
      _wsRetry++;
      setTimeout(connectWS, delay);
    };

    ws.onerror = () => ws.close();
  }

  let _wsRetry = 0;

  // ── UI dev hot-reload (polling the Web process — dev-only, self-contained) ───
  let _devBuildVersion: number | null = null;
  setInterval(async () => {
    try {
      const r = await fetch(`${webBase}/ui/dev/version`);
      if (!r.ok) return;
      const { version } = await r.json();
      if (_devBuildVersion === null) { _devBuildVersion = version; return; }
      if (version !== _devBuildVersion) window.location.reload();
    } catch {}
  }, 2000);

  let viewFormat = $state<"html" | "md">("html");
  let tree = $state<VaultTreeNode[]>([]);
  let collapsedDirs = $state<Set<string>>(new Set());
  let treeLoaded = $state(false);
  let sidebarEl = $state<HTMLElement | null>(null);
  let sidebarAsideEl = $state<HTMLElement | null>(null);

  // Sidebar width/collapse — persisted so the layout survives a reload.
  const SIDEBAR_MIN_WIDTH = 160;
  const SIDEBAR_MAX_WIDTH = 480;
  const SIDEBAR_DEFAULT_WIDTH = 220;
  // Real persisted value arrives async via loadSettings() -> cfg.sidebar_width
  // (see bootstrap() below) -- this is just the synchronous placeholder
  // $state needs at declaration time, same convention as apiBase/cfg.scale.
  let sidebarWidth = $state(SIDEBAR_DEFAULT_WIDTH);
  let sidebarCollapsed = $state(
    typeof window !== "undefined" && localStorage.getItem("prisma.sidebarCollapsed") === "1"
  );
  let sidebarResizing = $state(false);

  function toggleSidebarCollapsed() {
    sidebarCollapsed = !sidebarCollapsed;
    localStorage.setItem("prisma.sidebarCollapsed", sidebarCollapsed ? "1" : "0");
  }

  function startSidebarResize(e: MouseEvent) {
    e.preventDefault();
    sidebarResizing = true;
    // Measure from the sidebar's own left edge rather than assuming it sits
    // at viewport x=0.
    const sidebarLeft = sidebarAsideEl?.getBoundingClientRect().left ?? 0;
    const onMove = (ev: MouseEvent) => {
      sidebarWidth = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, ev.clientX - sidebarLeft));
    };
    const onUp = () => {
      sidebarResizing = false;
      cfg.sidebar_width = sidebarWidth;
      savePlatformSettings(cfg).catch(() => {});
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }
  // context menu
  let ctxMenu = $state<{ x: number; y: number; slug: string | null; title: string; dirKey: string | null; isChat?: boolean } | null>(null);
  let ctxMovePicker = $state(false);
  let renameTarget = $state<{ slug: string; value: string } | null>(null);
  // drag and drop
  let dragSlug = $state<string | null>(null);
  let dragOverKey = $state<string | null>(null);
  let hoverExpandTimer: ReturnType<typeof setTimeout> | null = null;
  let activeNode = $state<RenderedNode | null>(null);
  // <iframe src="..."> can't carry an Authorization header, so once
  // server.auth.mode is "password" a direct apiBase URL there would just
  // 401 — loaded as a blob URL via apiFetch instead. See the vault-sync
  // plan's note on this being the one real gap authFetch alone can't close.
  let htmlFrameSrc = $state<string | null>(null);
  $effect(() => {
    const node = activeNode;
    if (!node || node.original_ext !== ".html") {
      htmlFrameSrc = null;
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    (async () => {
      try {
        const r = await apiFetch(`${apiBase}/notes/${node.slug}/view`);
        if (!r.ok || cancelled) return;
        const blob = await r.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) htmlFrameSrc = objectUrl;
      } catch {}
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  });
  let activeChat = $state<ChatDetail | null>(null);
  let excerptPollInterval: ReturnType<typeof setInterval> | undefined;
  let chatInput = $state("");
  let chatSending = $state(false);
  // Turn indices whose tool-call/thought/recall "spin-offs" (the process
  // artifacts behind a reply, not the reply's own content) are expanded --
  // collapsed by default, since most turns don't need examining, but always
  // available on demand. Keyed by turn index, not persisted across chats.
  let expandedTurnDetails = $state(new Set<number>());

  function toggleTurnDetails(i: number) {
    const next = new Set(expandedTurnDetails);
    if (next.has(i)) next.delete(i); else next.add(i);
    expandedTurnDetails = next;
  }
  // GET /models: populates the regenerate model picker. `current` (the
  // chat's own configured model) is always included even if provider
  // discovery fails or returns nothing else -- see app.py's list_models.
  let availableModels = $state<string[]>([]);
  // Per-turn regenerate model choice ("" = no override, use the chat's
  // current model) -- keyed by turn index so multiple turns' pickers don't
  // clobber each other.
  let regenModelChoice = $state<Record<number, string>>({});
  // Which alternate (by its index into msg.alternates) is currently shown
  // expanded, per turn index -- null/absent = none expanded, the live
  // content is all that's shown (the pre-existing behavior).
  let expandedAlternate = $state<Record<number, number | null>>({});

  function toggleAlternate(turnIndex: number, altIndex: number) {
    const cur = expandedAlternate[turnIndex] ?? null;
    expandedAlternate = { ...expandedAlternate, [turnIndex]: cur === altIndex ? null : altIndex };
  }

  // asset_path is vault-root-relative with real '/' separators (e.g.
  // "chats/my-chat-attachments/abc.jpg") -- encode per-segment, not the
  // whole string, so '/' stays a path separator for GET /vault/assets/{path:path}.
  function vaultAssetUrl(assetPath: string): string {
    return `${apiBase}/vault/assets/${assetPath.split("/").map(encodeURIComponent).join("/")}`;
  }

  // <img src="..."> / <a href="..."> can't carry an Authorization header,
  // same gap htmlFrameSrc above already works around -- one shared blob-URL
  // cache instead of duplicating that per-node effect for every chat media
  // item across every turn. ensureAssetBlobUrl is idempotent (checked
  // before fetching), safe to call directly from template rendering.
  let assetBlobUrls = $state<Record<string, string>>({});
  function ensureAssetBlobUrl(assetPath: string) {
    if (assetBlobUrls[assetPath]) return;
    (async () => {
      try {
        const r = await apiFetch(vaultAssetUrl(assetPath));
        if (!r.ok) return;
        const blob = await r.blob();
        assetBlobUrls = { ...assetBlobUrls, [assetPath]: URL.createObjectURL(blob) };
      } catch { /* image/link just won't load */ }
    })();
  }

  async function loadAvailableModels() {
    try {
      const r = await apiFetch(`${apiBase}/models`);
      if (r.ok) {
        const data = await r.json();
        availableModels = data.models ?? [];
      }
    } catch { /* non-critical -- regenerate still works with no override */ }
  }
  let serverOnline = $state(false);
  let kgState = $state<GState | null>(null);
  let kgLastIndexed = $state<string | null>(null);
  let serverStatus = $state<ServerStatus | null>(null);
  type PoolStats = { granted: number; denied_capacity: number; denied_model_busy: number; denied_vram_budget: number };
  let previousResourceStats = $state<Record<string, PoolStats>>({});
  let recentResourceStats = $state<Record<string, PoolStats>>({});
  let statusPopoverOpen = $state(false);
  let showResourcesPage = $state(false);
  let showKgProgressPage = $state(false);
  let searchQuery = $state("");
  let searchResults = $state<SearchResult[]>([]);
  let searching = $state(false);
  let loadingNode = $state(false);

  let showDeepSearch = $state(false);
  let deepQuery = $state("");
  let deepInputEl = $state<HTMLInputElement | undefined>(undefined);
  let renameInputEl = $state<HTMLInputElement | undefined>(undefined);
  $effect(() => { if (showDeepSearch) deepInputEl?.focus(); });
  $effect(() => { if (renameTarget) renameInputEl?.focus(); });
  let deepResults = $state<DeepSearchResult[]>([]);
  let deepSearching = $state(false);
  let deepTimer: ReturnType<typeof setTimeout> | null = null;
  let deepPhase = $state(0);
  let deepPhaseTimer: ReturnType<typeof setInterval> | null = null;
  const DEEP_PHASES = ["Reading graph context…", "Asking Ollama…", "Ranking results…"];

  let streams = $state<StreamMeta[]>([]);
  let chats = $state<NodeMeta[]>([]);
  let sectionOpen = $state<Record<string, boolean>>({ vault: true, streams: true, chats: false, zotero: false, system: false });

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
    // Deliberately after the ping, not at component init (see removed
    // top-level call) -- apiBase is still the Tauri loopback placeholder
    // until loadSettings() resolves, so an eager connectWS() always fails
    // its first attempt against the wrong host.
    connectWS();
    await Promise.all([loadTree(), loadHome(), loadStreams(), loadChats(), loadZoteroStatus(), loadAvailableModels()]);
    pollStatus();
  }

  async function ping(): Promise<boolean> {
    try {
      const r = await apiFetch(`${apiBase}/health`, { signal: AbortSignal.timeout(2000) });
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
      const r = await apiFetch(`${apiBase}/tree`);
      if (r.ok) {
        tree = await r.json();
        if (!treeLoaded) { collapsedDirs = initCollapsed(tree); treeLoaded = true; }
      }
    } catch {}
  }

  async function moveNode(slug: string, destDir: string) {
    ctxMenu = null; ctxMovePicker = false;
    const r = await apiFetch(`${apiBase}/nodes/${encodeURIComponent(slug)}/move`, {
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
    const r = await apiFetch(`${apiBase}/nodes/${encodeURIComponent(slug)}/rename`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: value }),
    });
    if (r.ok) {
      const { slug: newSlug } = await r.json();
      await loadTree();
      if (activeNode?.slug === slug) await openNode(newSlug);
      if (activeChat?.slug === slug) {
        await loadChats();
        await openChat(newSlug);
      } else {
        await loadChats();
      }
    }
  }

  async function doDelete(slug: string) {
    ctxMenu = null;
    if (!confirm("Delete this item permanently?")) return;
    await apiFetch(`${apiBase}/nodes/${encodeURIComponent(slug)}`, { method: "DELETE" });
    await loadTree();
    await loadChats();
    if (activeNode?.slug === slug) activeNode = null;
    if (activeChat?.slug === slug) activeChat = null;
  }

  async function doCreateDir(parentKey: string) {
    ctxMenu = null;
    const name = prompt("New folder name:");
    if (!name?.trim()) return;
    const rel = (parentKey.startsWith("/") ? parentKey.slice(1) : parentKey) + "/" + name.trim();
    await apiFetch(`${apiBase}/dirs`, {
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
      const r = await apiFetch(`${apiBase}/streams`);
      if (r.ok) streams = await r.json();
    } catch {}
  }

  async function loadChats() {
    try {
      const r = await apiFetch(`${apiBase}/notes?node_type=chat`);
      if (r.ok) {
        const listing = await r.json();
        chats = listing.chats ?? [];
      }
    } catch {}
  }

  // ADR-020: slug -> APA-citation-string cache, populated on demand
  // whenever a chat's messages (could) contain new claim source slugs --
  // fetchApaCitations() only requests what's not already cached.
  let apaCitations = $state<Record<string, string>>({});

  async function fetchApaCitations(messages: ChatTurn[]) {
    const slugs = new Set<string>();
    for (const msg of messages) {
      for (const claim of msg.claims ?? []) {
        if (claim.kind === "claim") for (const s of claim.sources) slugs.add(s);
      }
    }
    const missing = [...slugs].filter(s => !(s in apaCitations));
    if (missing.length === 0) return;
    const r = await apiFetch(`${apiBase}/notes/apa?slugs=${missing.map(encodeURIComponent).join(",")}`);
    if (r.ok) apaCitations = { ...apaCitations, ...(await r.json()) };
  }

  async function openChat(slug: string) {
    clearInterval(excerptPollInterval);  // stop any poll for the chat we're leaving, immediately
    activeNode = null;
    showResourcesPage = false;
    showKgProgressPage = false;
    showSettings = false;
    loadingNode = true;
    try {
      const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(slug)}`);
      if (r.ok) {
        const chat: ChatDetail = await r.json();
        activeChat = chat;
        void fetchApaCitations(chat.messages);
      }
    } finally {
      loadingNode = false;
    }
  }

  async function createChat() {
    const r = await apiFetch(`${apiBase}/chats`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    if (r.ok) {
      const chat = await r.json();
      await loadChats();
      await openChat(chat.slug);
    }
  }

  // v3: attachments pending for the NEXT message, not yet sent -- cleared
  // once sendChatMessage() actually posts them. jpg/pdf go through
  // uploadFileAttachment() (ephemeral, L1/L2 -- see POST /chats/{slug}/
  // attachments/upload) first; svg/latex/drawio need no upload step, built
  // directly as an InlineMediaOut.
  let pendingAttachments = $state<MediaOut[]>([]);
  let pendingAttachedSlugs = $state<string[]>([]);
  let attachmentUploading = $state(false);
  let showInlineAttachForm = $state<"svg" | "latex" | "drawio" | null>(null);
  let inlineAttachValue = $state("");
  let slugAttachInput = $state("");

  async function uploadFileAttachment(file: File) {
    if (!activeChat) return;
    attachmentUploading = true;
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(activeChat.slug)}/attachments/upload`, {
        method: "POST", body: form,
      });
      if (r.ok) {
        const data = await r.json();
        pendingAttachments = [...pendingAttachments, data.attachment];
      } else {
        alert("Couldn't attach that file — must be a valid jpg or pdf.");
      }
    } finally {
      attachmentUploading = false;
    }
  }

  function onAttachmentFileChosen(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (file) void uploadFileAttachment(file);
  }

  function addInlineAttachment() {
    if (!showInlineAttachForm || !inlineAttachValue.trim()) return;
    // Client-generated id -- the server assigns its own real id once this
    // gets promoted or otherwise round-trips; this one only needs to be
    // locally unique for Svelte's #each keying and TS's InlineMediaOut shape.
    pendingAttachments = [...pendingAttachments, { id: crypto.randomUUID(), kind: showInlineAttachForm, value: inlineAttachValue, caption: null }];
    inlineAttachValue = "";
    showInlineAttachForm = null;
  }

  function addSlugAttachment() {
    const s = slugAttachInput.trim();
    if (!s || pendingAttachedSlugs.includes(s)) return;
    pendingAttachedSlugs = [...pendingAttachedSlugs, s];
    slugAttachInput = "";
  }

  function removePendingAttachment(idx: number) {
    pendingAttachments = pendingAttachments.filter((_, ix) => ix !== idx);
  }

  function removePendingSlug(idx: number) {
    pendingAttachedSlugs = pendingAttachedSlugs.filter((_, ix) => ix !== idx);
  }

  async function sendChatMessage() {
    if (!activeChat || !chatInput.trim() || chatSending) return;
    const text = chatInput;
    const slug = activeChat.slug;
    const attachments = pendingAttachments;
    const attachedSlugs = pendingAttachedSlugs;
    chatInput = "";
    pendingAttachments = [];
    pendingAttachedSlugs = [];
    chatSending = true;
    activeChat.messages = [
      ...activeChat.messages,
      {
        role: "user", content: { format: "md", value: text, rendered_html: null },
        timestamp: new Date().toISOString(), claims: [], thoughts: [], tool_calls: [], recalls: [],
        attachments, attached_slugs: attachedSlugs,
      },
    ];
    try {
      const r = await apiFetch(`${apiBase}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, chat_slug: slug, attachments, attached_slugs: attachedSlugs }),
      });
      if (r.ok && activeChat?.slug === slug) {
        const data = await r.json();
        activeChat.messages = [
          ...activeChat.messages,
          {
            role: "assistant", content: { format: "md", value: data.reply, rendered_html: data.html ?? null },
            timestamp: new Date().toISOString(), claims: data.claims ?? [], thoughts: [],
            tool_calls: data.tool_calls ?? [], recalls: data.recalls ?? [],
          },
        ];
        void fetchApaCitations(activeChat.messages);
      }
    } finally {
      chatSending = false;
    }
  }

  async function regenerateTurn(index: number, model?: string) {
    if (!activeChat || chatSending) return;
    const slug = activeChat.slug;
    chatSending = true;
    try {
      const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(slug)}/turns/${index}/regenerate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model ?? null }),
      });
      if (r.ok && activeChat?.slug === slug) {
        const chat: ChatDetail = await r.json();
        activeChat = chat;
        void fetchApaCitations(chat.messages);
      }
    } finally {
      chatSending = false;
    }
  }

  async function deleteChatMessage(index: number) {
    if (!activeChat) return;
    if (!confirm("Remove this turn from the conversation?")) return;
    const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(activeChat.slug)}/messages/${index}`, { method: "DELETE" });
    if (r.ok) activeChat = await r.json();
  }

  async function togglePinTurn(index: number) {
    if (!activeChat) return;
    const slug = activeChat.slug;
    const pinned = !activeChat.pinned_turns.includes(index);
    const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(slug)}/turns/${index}/pin`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    });
    if (r.ok) {
      activeChat = await r.json();
      // Regeneration runs in the background (a slow/GPU-contended
      // summarize() call must never block this request) — activeChat's
      // excerpt_summary_html still holds the *previous* Summary until
      // polling detects the new one is ready.
      await loadTree();
      if (activeChat?.excerpt_regenerating) pollExcerptRegeneration(slug);
    }
  }

  function pollExcerptRegeneration(slug: string) {
    // Stop any prior poll immediately rather than letting it self-clear on
    // its own next 2s tick — that gap is what let a stale poll fire one
    // wasted request against the wrong (or no-longer-active) chat right
    // after switching away.
    clearInterval(excerptPollInterval);
    excerptPollInterval = setInterval(async () => {
      if (!activeChat || activeChat.slug !== slug) { clearInterval(excerptPollInterval); return; }
      const r = await apiFetch(`${apiBase}/chats/${encodeURIComponent(slug)}`);
      if (!r.ok) { clearInterval(excerptPollInterval); return; }
      const fresh = await r.json();
      // Merge only the Excerpt-related fields — never replace the whole
      // object. A full replace here raced with sendChatMessage's optimistic
      // append: if this poll's fetch happened to land while a /chat request
      // was still in flight, `fresh.messages` wouldn't yet include the
      // user's just-sent turn, and assigning it wholesale made that message
      // visually vanish until the next reload.
      if (activeChat?.slug === slug) {
        activeChat = {
          ...activeChat,
          pinned_turns: fresh.pinned_turns,
          excerpt_slug: fresh.excerpt_slug,
          excerpt_regenerating: fresh.excerpt_regenerating,
          excerpt_summary_html: fresh.excerpt_summary_html,
          context_tokens_used: fresh.context_tokens_used,
          context_tokens_max: fresh.context_tokens_max,
        };
      }
      if (!fresh.excerpt_regenerating) clearInterval(excerptPollInterval);
    }, 2000);
  }

  function scrollToTurn(index: number) {
    const el = document.getElementById(`chat-turn-${index}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("chat-turn-flash");
    setTimeout(() => el.classList.remove("chat-turn-flash"), 1200);
  }

  function truncate(text: string, n: number): string {
    const oneLine = text.trim().replace(/\s+/g, " ");
    return oneLine.length > n ? oneLine.slice(0, n - 1) + "…" : oneLine;
  }

  async function loadZoteroStatus() {
    try {
      const r = await apiFetch(`${apiBase}/zotero/status`);
      if (r.ok) zoteroStatus = await r.json();
    } catch {}
  }

  async function loadZoteroCollections() {
    zoteroLoading = true;
    try {
      const r = await apiFetch(`${apiBase}/zotero/collections`);
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
      const r = await apiFetch(`${apiBase}/zotero/items?${params}`);
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
      const r = await apiFetch(`${apiBase}/zotero/import/${key}`, { method: "POST" });
      if (r.ok) {
        const node = await r.json();
        activeNode = node;
        await Promise.all([loadTree(), loadZoteroItems()]);
      }
    } catch {} finally { importingKey = null; }
  }

  async function loadHome() {
    activeChat = null;
    showResourcesPage = false;
    showKgProgressPage = false;
    showSettings = false;
    loadingNode = true;
    try {
      const r = await apiFetch(`${apiBase}/home`);
      if (r.ok) activeNode = await r.json();
    } catch {} finally { loadingNode = false; }
  }

  // ── Status polling ──────────────────────────────────────────────────────────

  function pollStatus() {
    fetchStatus();
    setInterval(fetchStatus, 10_000);
  }

  async function fetchStatus() {
    const wasOnline = serverOnline;
    try {
      const r = await apiFetch(`${apiBase}/status`, { signal: AbortSignal.timeout(3000) });
      if (!r.ok) { serverOnline = false; serverStatus = null; return; }
      const s: ServerStatus = await r.json();
      serverOnline = true;
      serverStatus = s;
      if (s.resources) {
        const deltas: Record<string, PoolStats> = {};
        for (const [name, pool] of Object.entries(s.resources)) {
          const prev = previousResourceStats[name];
          deltas[name] = prev
            ? {
                granted: pool.stats.granted - prev.granted,
                denied_capacity: pool.stats.denied_capacity - prev.denied_capacity,
                denied_model_busy: pool.stats.denied_model_busy - prev.denied_model_busy,
                denied_vram_budget: pool.stats.denied_vram_budget - prev.denied_vram_budget,
              }
            : { granted: 0, denied_capacity: 0, denied_model_busy: 0, denied_vram_budget: 0 };
        }
        recentResourceStats = deltas;
        previousResourceStats = Object.fromEntries(
          Object.entries(s.resources).map(([name, pool]) => [name, { ...pool.stats }]),
        );
      }
      kgState = s.knowledge_graph?.state ?? null;
      kgLastIndexed = s.knowledge_graph?.last_indexed ?? null;
      if (!wasOnline) {
        await Promise.all([loadTree(), loadHome(), loadStreams(), loadChats(), loadZoteroStatus(), loadAvailableModels()]);
      } else {
        await loadTree();
      }
    } catch { serverOnline = false; serverStatus = null; }
  }

  // ── Reload ──────────────────────────────────────────────────────────────────

  // Matches the supervisor's own worker set (prisma/server/supervisor.py's
  // `workers` dict) — see GET /supervisor/status, proxied to the UI as
  // serverStatus.processes.
  const WORKER_NAMES = ["api", "web", "chroma", "kg"] as const;
  type WorkerName = (typeof WORKER_NAMES)[number];
  type ReloadScope = "all" | WorkerName;
  let reloading = $state(false);
  let reloadScope = $state<ReloadScope>("all");

  function supervisorBase(): string {
    try {
      const url = new URL(apiBase);
      url.port = String(DEFAULT_SUPERVISOR_PORT);
      return url.origin;
    } catch {
      return `http://127.0.0.1:${DEFAULT_SUPERVISOR_PORT}`;
    }
  }

  async function restartWorker(name: WorkerName): Promise<void> {
    // Restarting "api" by proxying through the api process itself would
    // kill the very process handling this request before it can respond —
    // hit the supervisor's own loopback control port directly instead
    // (same reasoning the old code hit webBase directly for UI reloads
    // rather than proxying those through the api process either).
    if (name === "api") {
      await fetch(`${supervisorBase()}/supervisor/restart/api`, { method: "POST" });
    } else {
      await apiFetch(`${apiBase}/supervisor/restart/${name}`, { method: "POST" });
    }
  }

  async function reloadServer() {
    reloading = true;
    try {
      if (reloadScope === "all") {
        for (const name of WORKER_NAMES) await restartWorker(name);
      } else {
        await restartWorker(reloadScope);
      }
      if (reloadScope === "all" || reloadScope === "web") {
        window.location.reload();
      } else {
        await Promise.all([loadTree(), loadStreams(), loadChats(), loadZoteroStatus()]);
      }
    } catch {} finally { reloading = false; }
  }

  // ── Navigation ──────────────────────────────────────────────────────────────

  async function openNode(slug: string, fmt?: "html" | "md") {
    activeChat = null;
    showResourcesPage = false;
    showKgProgressPage = false;
    showSettings = false;
    loadingNode = true;
    try {
      const f = fmt ?? viewFormat;
      const url = f === "md" ? `${apiBase}/notes/${slug}?format=md` : `${apiBase}/notes/${slug}`;
      const r = await apiFetch(url);
      if (r.ok) activeNode = await r.json();
    } catch {} finally { loadingNode = false; }
  }

  async function openStream(slug: string) {
    activeChat = null;
    showResourcesPage = false;
    showKgProgressPage = false;
    showSettings = false;
    loadingNode = true;
    try {
      const r = await apiFetch(`${apiBase}/streams/${slug}/view`);
      if (r.ok) {
        activeNode = await r.json();
        if (activeNode?.collection_key) {
          zoteroCollection = activeNode.collection_key;
          if (zoteroStatus?.available) {
            zoteroLoading = true;
            try {
              if (zoteroCollections.length === 0) {
                const rc = await apiFetch(`${apiBase}/zotero/collections`);
                if (rc.ok) zoteroCollections = await rc.json();
              }
              const params = new URLSearchParams({ collection: activeNode.collection_key });
              const ri = await apiFetch(`${apiBase}/zotero/items?${params}`);
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
        await apiFetch(`${apiBase}/notes/${activeNode.slug}/md`, { method: "POST" });
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

  // Delegates clicks on links inside {@html}-rendered content. Attached imperatively
  // (rather than an onclick attribute) because the container is not itself an
  // interactive widget — only the <a> elements it hosts are, and those already carry
  // native link semantics and keyboard support.
  function contentClickDelegate(node: HTMLElement) {
    node.addEventListener("click", handleContentClick);
    return {
      destroy() {
        node.removeEventListener("click", handleContentClick);
      },
    };
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
      const r = await apiFetch(`${apiBase}/search?q=${encodeURIComponent(searchQuery)}`);
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
      const r = await apiFetch(`${apiBase}/search/deep?q=${encodeURIComponent(deepQuery)}`);
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

  import { untrack } from "svelte";

  function handleIframeMessage(e: MessageEvent) {
    if (e.data?.type === "open-url" && typeof e.data.url === "string") {
      shellOpen(e.data.url);
    }
  }
  window.addEventListener("message", handleIframeMessage);

  const SCALE_MIN = 1.0;
  const SCALE_MAX = 5.0;
  const SCALE_STEP = 0.05;

  let showSettings = $state(false);
  // Real persisted value arrives async via loadSettings() below -- this is
  // just the synchronous placeholder $state needs at declaration time,
  // parsed from apiBase's own placeholder (see _defaultApiBase()) so it's
  // at least self-consistent until then.
  let cfg = $state<AppSettings>(untrack(() => {
    const url = new URL(apiBase);
    return {
      scale: DEFAULT_SCALE,
      hostname: url.hostname,
      tls: url.protocol === "https:",
      api_port: Number(url.port) || (url.protocol === "https:" ? 443 : 80),
      web_port: DEFAULT_WEB_PORT,
      vault_path: null,
      sidebar_width: SIDEBAR_DEFAULT_WIDTH,
    };
  }));
  let syncStatus = $state<SyncStatusInfo>({ running: false, server_url: null, vault_path: null, tracked_files: 0, needs_reauth: false });
  // Non-null only when the last applySyncPolicy()/syncStart() call actively
  // refused to start (e.g. prisma-desktop's same-filesystem collision
  // guard) -- distinct from the ordinary "stopped because Local" case,
  // which needs no explanation.
  let syncBlockedReason = $state<string | null>(null);
  let syncDiffInfo = $state<SyncDiffInfo | null>(null);
  let syncDiffLoading = $state(false);

  let chatSystemPrompt = $state("");
  let chatSystemPromptLoading = $state(false);
  let chatSystemPromptSaving = $state(false);
  let chatSystemPromptSaved = $state(false);

  async function loadChatSystemPrompt() {
    chatSystemPromptLoading = true;
    try {
      const r = await apiFetch(`${apiBase}/chat/system-prompt`);
      chatSystemPrompt = (await r.json()).content;
    } catch { /* leave the field blank rather than clobber a load-in-progress edit */ }
    chatSystemPromptLoading = false;
  }

  async function saveChatSystemPrompt() {
    chatSystemPromptSaving = true;
    chatSystemPromptSaved = false;
    try {
      const r = await apiFetch(`${apiBase}/chat/system-prompt`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: chatSystemPrompt }),
      });
      chatSystemPrompt = (await r.json()).content;
      chatSystemPromptSaved = true;
      setTimeout(() => { chatSystemPromptSaved = false; }, 2000);
    } catch { /* button label falls back to "Save" below; no toast system to report the failure through */ }
    chatSystemPromptSaving = false;
  }

  async function refreshSyncInfo() {
    syncStatus = await syncEngineStatus();
    syncDiffLoading = true;
    syncDiffInfo = await syncDiff();
    syncDiffLoading = false;
  }

  async function chooseVaultFolder() {
    const folder = await pickVaultFolder();
    if (!folder) return;
    cfg.vault_path = folder;
    try { await savePlatformSettings(cfg); } catch {}
    // Restart (not just leave running) so the engine picks up the new
    // vault_path immediately instead of on next app launch.
    await syncStop();
    syncBlockedReason = await applySyncPolicy(apiBase);
    await refreshSyncInfo();
  }

  // Refreshes whenever the Settings page is opened — not continuously
  // polled, since this is a manual-refresh status view, not a live feed.
  $effect(() => {
    if (showSettings && isTauri) refreshSyncInfo();
  });

  // Unlike the sync status above, this applies to every server (Tauri
  // desktop and plain web UI alike) — the file it reads/writes lives on
  // whichever machine is running `prisma serve`, not the client.
  $effect(() => {
    if (showSettings) loadChatSystemPrompt();
  });

  async function loadSettings() {
    // Retries rather than silently keeping apiBase's Local placeholder on a
    // single failed attempt -- confirmed live 2026-07-26: a transient
    // invoke("get_settings") failure this early in Tauri startup left
    // apiBase stuck at Local for the entire session (sync correctly never
    // started, since Local means "don't sync" by design, but the user was
    // actually configured for a remote server the whole time with no
    // visible indication anything was wrong).
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        cfg = await loadPlatformSettings();
        apiBase = cfg.hostname ? apiUrl(cfg) : apiBase;
        sidebarWidth = cfg.sidebar_width || SIDEBAR_DEFAULT_WIDTH;
        break;
      } catch (err) {
        console.error(`loadSettings: attempt ${attempt}/3 failed`, err);
        if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 200));
      }
    }
    // Apply on every load/restart, not just after clicking Save in
    // Settings — previously the persisted scale was loaded into `cfg` but
    // never actually applied until the user re-opened Settings and hit
    // Save, so every fresh launch silently reset back to the platform's
    // native 1x regardless of what was saved.
    try {
      await applyScale(cfg.scale);
    } catch {}
  }

  async function saveAndApply() {
    // The hostname/TLS/port fields only exist in the Tauri Settings card
    // (isTauri-gated, see the "Server" resource-card below) -- in
    // browser/PWA mode cfg.hostname is never populated by the user, so
    // deriving apiBase from cfg here would overwrite the real, working
    // apiBase with the empty "http://:0" placeholder on every single save.
    if (isTauri) apiBase = apiUrl(cfg);
    try {
      await savePlatformSettings(cfg);
      await applyScale(cfg.scale);
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
      const r = await apiFetch(`${apiBase}/streams`, {
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
    await apiFetch(`${apiBase}/streams/${slug}`, { method: "DELETE" });
    if (activeNode?.slug === slug) activeNode = null;
    await Promise.all([loadTree(), loadStreams()]);
  }

  async function patchStreamStatus(slug: string, status: string) {
    await apiFetch(`${apiBase}/streams/${slug}`, {
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

{#if showLoginScreen}
  <LoginScreen serverUrl={apiBase} onLoggedIn={() => { showLoginScreen = false; loadTree(); connectWS(); }} />
{/if}

<div class="shell">

  <!-- Workspace -->
  <div class="workspace">

    <!-- Sidebar -->
    <aside
      class="sidebar"
      class:collapsed={sidebarCollapsed}
      bind:this={sidebarAsideEl}
      style={sidebarCollapsed ? "" : `width: ${sidebarWidth}px`}
    >
      {#if !sidebarCollapsed}
      <button class="home-btn" class:active={activeNode?.slug === "home"} onclick={loadHome}>
        Home
      </button>
      <div class="sidebar-search">
        <div class="search-wrap">
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
      </div>
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
                <svg class="tree-dir-icon" viewBox="0 0 24 24" fill="currentColor">
                  {#if open}
                    <path d="M3 6h6l2 2h10v2H3V6Z" opacity="0.55"/>
                    <path d="M2 10h19l-2 9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1L2 10Z"/>
                  {:else}
                    <path d="M3 6h6l2 2h10v11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z"/>
                  {/if}
                </svg>
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

        <!-- Vault section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("vault")}>
            <span class="section-chevron" class:open={sectionOpen.vault}>{sectionOpen.vault ? "▾" : "▸"}</span>
            <span class="section-label">Notes and Sources</span>
          </button>
        </div>
        {#if sectionOpen.vault}
          <div class="section-body" role="list" bind:this={sidebarEl} ondragover={onSidebarDragOver}>
            {#if tree.length > 0}
              {#each tree as node}
                {@render treeNode(node, "")}
              {/each}
            {:else}
              <div class="sidebar-empty">No notes or sources yet</div>
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
          <button class="section-action" onclick={() => createChat()}>+</button>
        </div>
        {#if sectionOpen.chats}
          <div class="section-body">
            {#if chats.length > 0}
              {#each chats as c}
                <button
                  class="tree-file"
                  class:active={activeChat?.slug === c.slug}
                  onclick={() => openChat(c.slug)}
                  oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, slug: c.slug, title: c.title, dirKey: null, isChat: true }; ctxMovePicker = false; }}
                >
                  <span class="tree-type-dot nt-chat"></span>
                  <span class="tree-file-name">{c.title}</span>
                </button>
              {/each}
            {:else}
              <div class="sidebar-empty">No chats yet — press + to start one</div>
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
          <div class="section-body zotero-panel">
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

        <!-- System section -->
        <div class="section-header">
          <button class="section-toggle" onclick={() => toggleSection("system")}>
            <span class="section-chevron" class:open={sectionOpen.system}>{sectionOpen.system ? "▾" : "▸"}</span>
            <span class="section-label">System</span>
          </button>
        </div>
        {#if sectionOpen.system}
          <div class="section-body">
            <button
              class="tree-file"
              class:active={showResourcesPage}
              onclick={() => { clearInterval(excerptPollInterval); activeNode = null; activeChat = null; showResourcesPage = true; showKgProgressPage = false; showSettings = false; }}
            >
              <span class="tree-type-dot nt-stream"></span>
              <span class="tree-file-name">Compute pools</span>
            </button>
            <button
              class="tree-file"
              class:active={showKgProgressPage}
              onclick={() => { clearInterval(excerptPollInterval); activeNode = null; activeChat = null; showResourcesPage = false; showKgProgressPage = true; showSettings = false; }}
            >
              <span class="tree-type-dot nt-stream"></span>
              <span class="tree-file-name">Knowledge Graph</span>
            </button>
            <button
              class="tree-file"
              class:active={showSettings}
              onclick={() => { clearInterval(excerptPollInterval); activeNode = null; activeChat = null; showResourcesPage = false; showKgProgressPage = false; showSettings = true; }}
            >
              <span class="tree-type-dot nt-stream"></span>
              <span class="tree-file-name">Settings</span>
            </button>
          </div>
        {/if}
      {/if}

      <div class="sidebar-footer">
        <button
          class="icon-btn"
          onclick={() => { activeNode = null; activeChat = null; showResourcesPage = false; showKgProgressPage = false; showSettings = !showSettings; }}
          title="Settings"
        >⚙</button>

        <div class="status-anchor">
          <button
            class="gdot-btn"
            class:offline={!serverOnline}
            class:error={serverOnline && !serverStatus?.config?.ok}
            class:indexing={serverOnline && serverStatus?.config?.ok && kgState === "indexing"}
            class:stale={serverOnline && serverStatus?.config?.ok && kgState === "stale"}
            class:idle={serverOnline && serverStatus?.config?.ok && kgState === "idle"}
            onclick={() => statusPopoverOpen = !statusPopoverOpen}
            title="System status"
          ></button>
          {#if statusPopoverOpen}
            <button class="status-backdrop" aria-label="Close" onclick={() => statusPopoverOpen = false}></button>
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

                {#if serverStatus.chat_config}
                  <div class="sp-section">
                    <span class="sp-label">Chat</span>
                    <span class="sp-val ok">{serverStatus.chat_config.provider} / {serverStatus.chat_config.model}</span>
                  </div>
                {/if}

                {#if serverStatus.llm_backend}
                  <div class="sp-section">
                    <span class="sp-label">{LLM_BACKEND_LABELS[serverStatus.llm_backend.provider] ?? serverStatus.llm_backend.provider}</span>
                    <span class="sp-val" class:ok={serverStatus.llm_backend.reachable} class:bad={!serverStatus.llm_backend.reachable}>
                      {serverStatus.llm_backend.reachable ? "reachable" : "offline"}
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
                  <span class="sp-label">Knowledge graph</span>
                  <span class="sp-val"
                    class:ok={kgState === "idle"}
                    class:warn={kgState === "stale"}
                    class:info={kgState === "indexing"}
                  >
                    {kgState ?? "—"}
                    {#if kgLastIndexed && kgState === "idle"}
                      · {new Date(kgLastIndexed).toLocaleTimeString()}
                    {/if}
                  </span>
                </div>
                {#if serverStatus.knowledge_graph?.last_error}
                  <div class="sp-error">{serverStatus.knowledge_graph.last_error}</div>
                {/if}
                {#if serverStatus.knowledge_graph?.current_activity}
                  <div class="sp-vault-root">{serverStatus.knowledge_graph.current_activity}</div>
                {/if}

                {#if serverStatus.chroma}
                  <div class="sp-section">
                    <span class="sp-label">Chroma</span>
                    <span class="sp-val" class:ok={serverStatus.chroma.chunks > 0} class:warn={serverStatus.chroma.chunks === 0}>
                      {serverStatus.chroma.chunks} chunks · {serverStatus.chroma.files_indexed} files
                    </span>
                  </div>
                  <div class="sp-vault-root">{serverStatus.chroma.model}{serverStatus.chroma.provider ? ` (${serverStatus.chroma.provider})` : ""}</div>
                  {#if serverStatus.chroma.current_activity}
                    <div class="sp-vault-root">{serverStatus.chroma.current_activity}</div>
                  {/if}
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
                  {#if serverStatus.zotero.available && serverStatus.zotero.reachable !== undefined}
                    <div class="sp-vault-root">
                      Web API:
                      <span class:ok={serverStatus.zotero.reachable} class:warn={!serverStatus.zotero.reachable}>
                        {serverStatus.zotero.reachable ? "reachable" : "unreachable"}
                      </span>
                    </div>
                  {/if}
                {/if}

                {#if serverStatus.pending_jobs > 0}
                  <div class="sp-section">
                    <span class="sp-label">Jobs</span>
                    <span class="sp-val warn">{serverStatus.pending_jobs} pending</span>
                  </div>
                {/if}

                {#if serverStatus.processes}
                  <div class="sp-section">
                    <span class="sp-label">Processes</span>
                    <span class="sp-val">
                      {#if serverStatus.processes.system}
                        {serverStatus.processes.system.cpu_count} cores
                        {#if serverStatus.processes.system.memory_available_mb != null}
                          · {Math.round(serverStatus.processes.system.memory_available_mb / 1024 * 10) / 10}GB free
                          / {Math.round((serverStatus.processes.system.memory_total_mb ?? 0) / 1024 * 10) / 10}GB
                        {/if}
                      {/if}
                    </span>
                  </div>
                  {#each Object.entries(serverStatus.processes).filter(([k]) => k !== "system") as [name, proc]}
                    {#if proc && typeof proc === "object" && "pid" in proc}
                      <div class="sp-proc-row">
                        <span class="sp-proc-name" class:bad={!proc.alive}>{name}</span>
                        <span class="sp-proc-mem">{proc.memory_mb != null ? `${proc.memory_mb}MB` : "—"}</span>
                      </div>
                    {/if}
                  {/each}
                {/if}
              {/if}
            </div>
          {/if}
        </div>
      </div>
      {/if}
    </aside>
    {#if !sidebarCollapsed}
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="sidebar-resizer"
        class:resizing={sidebarResizing}
        onmousedown={startSidebarResize}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
      ></div>
    {/if}
    <button
      class="sidebar-collapse-btn"
      class:collapsed={sidebarCollapsed}
      title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
      onclick={toggleSidebarCollapsed}
    >
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style={sidebarCollapsed ? "transform: rotate(180deg)" : ""}>
        <polyline points="15 6 9 12 15 18"/>
      </svg>
    </button>

    <!-- Main -->
    <main class="main">
      {#if !serverOnline}
        <div class="empty-state">
          <p class="text-body">Prisma server is not running.</p>
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
              const r = await apiFetch(`${apiBase}/notes/${activeNode.slug}/type`, {
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
          {#if htmlFrameSrc}
          <iframe
            class="html-frame"
            src={htmlFrameSrc}
            title={activeNode.title}
          ></iframe>
          {/if}
          {/key}
        {:else}
        <div class="rendered" use:contentClickDelegate>
          {@html activeNode.html}
        </div>
        {/if}
      {:else if activeChat}
        <div class="chat-view">
          <div class="chat-conversation">
            <div class="chat-header">
              <span class="node-heading">{activeChat.title}</span>
              <span class="chat-model" title="Configured chat model/pool">{serverStatus?.chat_config?.model ?? activeChat.model}{#if serverStatus?.chat_config?.pool} · {serverStatus.chat_config.pool}{/if}</span>
              <span class="chat-context-usage" title="Session context usage vs. the configured rolling-history budget">{formatTokenCount(activeChat.context_tokens_used)} / {formatTokenCount(activeChat.context_tokens_max)}</span>
            </div>
            {#snippet mediaItem(m: MediaOut, role: "produced" | "attached")}
              {#if m.kind === "jpg"}
                {@const _ = ensureAssetBlobUrl(m.asset_path)}
                {#if assetBlobUrls[m.asset_path]}
                  <img class="chat-media-jpg" src={assetBlobUrls[m.asset_path]} alt={m.caption ?? "attached image"} title={m.caption ?? undefined} />
                {/if}
              {:else if m.kind === "pdf"}
                {@const _ = ensureAssetBlobUrl(m.asset_path)}
                {#if assetBlobUrls[m.asset_path]}
                  <a class="chat-media-pdf-link" href={assetBlobUrls[m.asset_path]} target="_blank" rel="noopener">📎 {m.caption ?? "attached.pdf"}</a>
                {/if}
              {:else}
                {@const inline = m as InlineMediaOut}
                <div class="chat-media-inline">
                  <div class="chat-media-inline-label">{inline.kind}{#if inline.caption} · {inline.caption}{/if} — {role === "produced" ? "generated" : "attached"}, not rendered yet</div>
                  <pre class="chat-media-inline-code">{inline.value}</pre>
                </div>
              {/if}
            {/snippet}
            <div class="chat-turns">
              {#if activeChat.messages.length === 0}
                <div class="empty-state"><p class="text-body">Ask anything about your vault.</p></div>
              {/if}
              {#each activeChat.messages as msg, i (i)}
                <div class="chat-turn chat-turn-{msg.role}" id="chat-turn-{i}">
                  <div class="chat-turn-header">
                    <span class="chat-turn-role">{msg.role === "user" ? "You" : "Prisma"}</span>
                    <span class="chat-turn-actions">
                      <button
                        class="chat-turn-action chat-pin-toggle"
                        class:pinned={activeChat?.pinned_turns.includes(i)}
                        title={activeChat?.pinned_turns.includes(i) ? "Unpin from Excerpt" : "Pin to Excerpt"}
                        onclick={() => togglePinTurn(i)}
                      >
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                          <path d="M12 21s-7-6.5-7-11a7 7 0 0 1 14 0c0 4.5-7 11-7 11z"/>
                        </svg>
                      </button>
                      {#if msg.role === "assistant"}
                        {#if availableModels.length > 1}
                          <select
                            class="chat-regen-model-picker"
                            title="Model to use if you regenerate this reply (blank = chat's current model)"
                            disabled={chatSending}
                            bind:value={regenModelChoice[i]}
                          >
                            <option value="">current model</option>
                            {#each availableModels as m}
                              <option value={m}>{m}</option>
                            {/each}
                          </select>
                        {/if}
                        <button
                          class="chat-turn-action"
                          title="Regenerate this reply"
                          disabled={chatSending}
                          onclick={() => regenerateTurn(i, regenModelChoice[i] || undefined)}
                        >
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                            <path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.75 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35Z"/>
                          </svg>
                        </button>
                      {/if}
                      <button class="chat-turn-action" title="Delete this turn" onclick={() => deleteChatMessage(i)}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                          <rect x="9" y="3" width="6" height="2" rx="1"/>
                          <rect x="4" y="6" width="16" height="2" rx="1"/>
                          <path d="M6 9h12l-1 11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L6 9Z"/>
                        </svg>
                      </button>
                    </span>
                  </div>
                  {#if msg.tool_calls?.length || msg.thoughts?.length || msg.recalls?.length}
                    {@const detailsOpen = expandedTurnDetails.has(i)}
                    <button class="chat-turn-details-toggle" onclick={() => toggleTurnDetails(i)}>
                      <span class="chat-turn-details-arrow" class:expanded={detailsOpen}>▸</span>
                      {summarizeTurnDetails(msg)}
                    </button>
                    {#if detailsOpen}
                      <div class="chat-turn-details">
                        {#if msg.tool_calls?.length}
                          <div class="chat-node-group chat-node-group-toolcalls">
                            <div class="chat-node-group-heading">Tool Calls</div>
                            <ol class="chat-node-group-list">
                              {#each msg.tool_calls as tc}
                                <li class="node-box node-box-toolcall" class:node-box-error={tc.status === "error"}>
                                  <code>{tc.tool}</code>{#if tc.args?.query}: {tc.args.query}{/if}
                                  {#if tc.result}
                                    <div class="node-box-toolcall-result">{tc.result}</div>
                                  {/if}
                                </li>
                              {/each}
                            </ol>
                          </div>
                        {/if}
                        {#if msg.thoughts?.length}
                          <div class="chat-node-group chat-node-group-thoughts">
                            <div class="chat-node-group-heading">Reasoning</div>
                            <ol class="chat-node-group-list">
                              {#each msg.thoughts as th}
                                <li class="node-box node-box-thought">#{th.thought_number}: {th.thought}</li>
                              {/each}
                            </ol>
                          </div>
                        {/if}
                        {#if msg.recalls?.length}
                          <div class="chat-node-group chat-node-group-recalls">
                            <div class="chat-node-group-heading">Recalled</div>
                            <ol class="chat-node-group-list">
                              {#each msg.recalls as r}
                                <li class="node-box node-box-recall">{r.node_kind}{#if r.chat_slug} · from another chat{/if}</li>
                              {/each}
                            </ol>
                          </div>
                        {/if}
                      </div>
                    {/if}
                  {/if}
                  <div class="chat-turn-content text-body">
                    {#each renderContentSegments(msg.content.value) as seg}
                      {#if "text" in seg}{seg.text}{:else}
                        {@const claim = msg.claims?.find(c => c.index === seg.claimIndex)}
                        <button
                          class="claim-ref claim-ref-{claim ? claimStyleKey(claim) : ''}"
                          title="Jump to claim {seg.claimIndex}"
                          onclick={() => document.getElementById(`chat-turn-${i}-claim-${seg.claimIndex}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
                        >{seg.claimIndex}</button>
                      {/if}
                    {/each}
                  </div>
                  {#if msg.media?.length || msg.attachments?.length || msg.attached_slugs?.length}
                    <div class="chat-media-list">
                      {#each msg.media ?? [] as m}{@render mediaItem(m, "produced")}{/each}
                      {#each msg.attachments ?? [] as m}{@render mediaItem(m, "attached")}{/each}
                      {#each msg.attached_slugs ?? [] as slug}
                        <button class="chat-media-slug" title="Referenced vault node" onclick={() => openNode(slug)}>📄 {slug}</button>
                      {/each}
                    </div>
                  {/if}
                  {#if msg.alternates?.length}
                    <div class="chat-turn-alternates" title="Earlier attempts at this turn, preserved when regenerated — click a model to view it">
                      {msg.alternates.length + 1} attempts —
                      <button
                        class="chat-turn-alternate-model"
                        class:active={expandedAlternate[i] == null}
                        onclick={() => (expandedAlternate = { ...expandedAlternate, [i]: null })}
                      >{msg.model ?? "current model"} (shown)</button>
                      {#each msg.alternates as alt, ai}
                        <button
                          class="chat-turn-alternate-model"
                          class:active={expandedAlternate[i] === ai}
                          onclick={() => toggleAlternate(i, ai)}
                        >· {alt.model ?? "unknown model"}</button>
                      {/each}
                    </div>
                    {#if expandedAlternate[i] != null && msg.alternates[expandedAlternate[i]]}
                      {@const alt = msg.alternates[expandedAlternate[i]]}
                      <div class="chat-turn-alternate-content text-body">
                        <div class="chat-turn-alternate-content-label">{alt.model ?? "unknown model"}'s attempt:</div>
                        {#each renderContentSegments(alt.content.value) as seg}{#if "text" in seg}{seg.text}{/if}{/each}
                      </div>
                    {/if}
                  {/if}
                  {#if msg.claims?.length}
                    <div class="chat-claims">
                      <div class="chat-claims-heading">References</div>
                      <ol class="chat-claims-list">
                        {#each msg.claims as claim}
                          <li class="claim-box claim-box-{claimStyleKey(claim)}" id="chat-turn-{i}-claim-{claim.index}">
                            <span class="claim-index">{claim.index}</span>
                            <span class="claim-relation claim-relation-{claimStyleKey(claim)}">{claimLabel(claim)}</span>
                            {#if claim.qualifier}
                              <span class="claim-qualifier" title="Epistemic strength (Toulmin qualifier)">{claim.qualifier}</span>
                            {/if}
                            {#if claim.rebuts}
                              <button
                                class="claim-rebuts"
                                title="Rebuts claim #{claim.rebuts} — click to jump to it"
                                onclick={() => document.getElementById(`chat-turn-${i}-claim-${claim.rebuts}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
                              >⤺ rebuts</button>
                            {/if}
                            {#if claim.warrant}
                              <div class="claim-warrant" title="Toulmin warrant — why the grounds support this claim">
                                <span class="claim-warrant-label">Warrant:</span> {claim.warrant.text}
                                {#if claim.warrant.backing.length}
                                  <span class="claim-warrant-backing">(backed by {#each claim.warrant.backing as s, si}{#if si > 0}, {/if}<button class="claim-source-link" onclick={() => openNode(s)}>{s}</button>{/each})</span>
                                {/if}
                              </div>
                            {/if}
                            {#if claim.kind === "claim" && claim.faithfulness_checked !== null}
                              <span
                                class="claim-faithfulness"
                                class:faithful={claim.faithfulness_checked}
                                class:unfaithful={!claim.faithfulness_checked}
                                title={claim.faithfulness_checked ? "Automated check: claim is supported by the cited source(s)" : "Automated check: claim does NOT appear to be supported by the cited source(s)"}
                              >{claim.faithfulness_checked ? "✓ verified" : "⚠ unsupported"}</span>
                            {/if}
                            {#if claim.kind === "claim" && claim.sources.length}
                              <div class="claim-sources">
                                {#each claim.sources as slug, si}{#if si > 0}, {/if}<button class="claim-source-link" onclick={() => openNode(slug)}>{slug}</button>{/each}
                              </div>
                              {#each claim.sources as slug}
                                {#if apaCitations[slug]}
                                  <div class="claim-apa">{apaCitations[slug]}</div>
                                {/if}
                              {/each}
                            {/if}
                          </li>
                        {/each}
                      </ol>
                    </div>
                  {/if}
                </div>
              {/each}
              {#if chatSending}
                <div class="chat-turn chat-turn-assistant chat-turn-pending">
                  <span class="spinner"></span>
                </div>
              {/if}
            </div>
            {#if pendingAttachments.length || pendingAttachedSlugs.length}
              <div class="chat-pending-attachments">
                {#each pendingAttachments as a, ai}
                  <span class="chat-pending-chip">
                    {a.kind === "jpg" ? "🖼️" : a.kind === "pdf" ? "📎" : "📝"} {a.kind}
                    <button type="button" class="chat-pending-chip-remove" onclick={() => removePendingAttachment(ai)}>×</button>
                  </span>
                {/each}
                {#each pendingAttachedSlugs as s, si}
                  <span class="chat-pending-chip">
                    📄 {s}
                    <button type="button" class="chat-pending-chip-remove" onclick={() => removePendingSlug(si)}>×</button>
                  </span>
                {/each}
              </div>
            {/if}
            {#if showInlineAttachForm}
              <div class="chat-attach-inline-form">
                <textarea
                  class="chat-attach-inline-textarea"
                  placeholder={showInlineAttachForm === "svg" ? "<svg>…</svg>" : showInlineAttachForm === "latex" ? "\\begin{equation}…\\end{equation}" : "<mxGraphModel>…</mxGraphModel>"}
                  bind:value={inlineAttachValue}
                ></textarea>
                <div class="chat-attach-inline-actions">
                  <button type="button" class="chat-turn-action" onclick={addInlineAttachment} disabled={!inlineAttachValue.trim()}>Add {showInlineAttachForm}</button>
                  <button type="button" class="chat-turn-action" onclick={() => { showInlineAttachForm = null; inlineAttachValue = ""; }}>Cancel</button>
                </div>
              </div>
            {/if}
            <form class="chat-input-row" onsubmit={(e) => { e.preventDefault(); sendChatMessage(); }}>
              <div class="chat-attach-toolbar">
                <label class="chat-attach-btn" title="Attach a jpg or pdf">
                  📎
                  <input type="file" accept=".jpg,.jpeg,.pdf,image/jpeg,application/pdf" hidden onchange={onAttachmentFileChosen} disabled={attachmentUploading || chatSending} />
                </label>
                <button type="button" class="chat-attach-btn" title="Attach SVG source" onclick={() => (showInlineAttachForm = showInlineAttachForm === "svg" ? null : "svg")}>SVG</button>
                <button type="button" class="chat-attach-btn" title="Attach LaTeX source" onclick={() => (showInlineAttachForm = showInlineAttachForm === "latex" ? null : "latex")}>TeX</button>
                <button type="button" class="chat-attach-btn" title="Attach draw.io XML" onclick={() => (showInlineAttachForm = showInlineAttachForm === "drawio" ? null : "drawio")}>Draw</button>
                <input
                  class="chat-attach-slug-input"
                  type="text"
                  placeholder="vault slug…"
                  title="Reference an existing vault node"
                  bind:value={slugAttachInput}
                  onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSlugAttachment(); } }}
                />
                {#if attachmentUploading}<span class="spinner chat-attach-spinner"></span>{/if}
              </div>
              <input
                class="chat-input"
                type="text"
                placeholder="Ask about your vault…"
                bind:value={chatInput}
                disabled={chatSending}
              />
              <button class="chat-send-btn" type="submit" disabled={chatSending || !chatInput.trim()}>Send</button>
            </form>
          </div>
          <div class="chat-notes-panel">
            <div class="chat-notes-header">
              <span class="chat-notes-title">Excerpt</span>
              {#if activeChat.excerpt_regenerating}
                <span class="chat-notes-regenerating" title="Regenerating the Excerpt in the background — showing the previous version until it's ready">
                  <svg class="spin" viewBox="0 0 24 24" width="11" height="11" fill="currentColor">
                    <path d="M12 12V3a9 9 0 1 1-9 9Z"/>
                  </svg>
                  regenerating…
                </span>
              {/if}
              <span class="chat-notes-count">{activeChat.pinned_turns.length}</span>
            </div>
            <div class="chat-notes-summary">
              {#if activeChat.excerpt_summary_html}
                <div class="rendered" use:contentClickDelegate>{@html activeChat.excerpt_summary_html}</div>
              {:else}
                <div class="empty-state chat-notes-empty">
                  <p class="text-body">Nothing pinned yet — pin a turn to start this chat's Excerpt, durable across this chat even after older turns roll off.</p>
                </div>
              {/if}
            </div>
            {#if activeChat.pinned_turns.length > 0}
              <div class="chat-notes-pinned-list">
                <div class="chat-notes-subheading">Pinned turns</div>
                {#each activeChat.pinned_turns as idx (idx)}
                  <button class="pinned-turn-item" onclick={() => scrollToTurn(idx)}>
                    <span class="pinned-turn-role">{activeChat.messages[idx]?.role === "user" ? "You" : "Prisma"}</span>
                    <span class="pinned-turn-preview">{truncate(activeChat.messages[idx]?.content?.value ?? "", 70)}</span>
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {:else if showResourcesPage}
        <div class="resources-page">
          <div class="node-toolbar">
            <span class="node-heading">Compute pools</span>
          </div>
          <div class="resources-body">
            {#if !serverStatus?.resources}
              <div class="empty-state"><p class="text-body">Resource status unavailable.</p></div>
            {:else}
              {#each Object.entries(serverStatus.resources) as [name, pool]}
                <div class="resource-card">
                  <div class="resource-card-header">
                    <span class="resource-pool-icon" title={pool.type}>
                      {#if pool.type === "gpu"}
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                          <rect x="6" y="6" width="12" height="12" rx="1"/>
                          <rect x="9.5" y="9.5" width="5" height="5" fill="#0d1420"/>
                          <rect x="2" y="8.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="2" y="11.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="2" y="14.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="18" y="8.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="18" y="11.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="18" y="14.25" width="4" height="1.5" rx="0.5"/>
                          <rect x="8.25" y="2" width="1.5" height="4" rx="0.5"/>
                          <rect x="11.25" y="2" width="1.5" height="4" rx="0.5"/>
                          <rect x="14.25" y="2" width="1.5" height="4" rx="0.5"/>
                          <rect x="8.25" y="18" width="1.5" height="4" rx="0.5"/>
                          <rect x="11.25" y="18" width="1.5" height="4" rx="0.5"/>
                          <rect x="14.25" y="18" width="1.5" height="4" rx="0.5"/>
                        </svg>
                      {:else}
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                          <path d="M7 16a4 4 0 0 1-1-7.9 5 5 0 0 1 9.6-2.4A4.5 4.5 0 0 1 20 10a4 4 0 0 1-1 6H7z"/>
                          <rect x="7.25" y="17" width="1.5" height="3" rx="0.75"/>
                          <circle cx="8" cy="21" r="1"/>
                          <rect x="13.25" y="17" width="1.5" height="3" rx="0.75"/>
                          <circle cx="14" cy="21" r="1"/>
                        </svg>
                      {/if}
                    </span>
                    <span class="resource-pool-name">{name}</span>
                    <div class="resource-pool-capacity-group">
                      {#if Object.keys(pool.model_capacity).length > 0}
                        {#each Object.entries(pool.model_capacity) as [model, mc]}
                          <span class="resource-pool-capacity" class:warn={mc.in_use >= mc.limit} title={model}>
                            {model}: {mc.in_use} / {mc.limit}
                          </span>
                        {/each}
                      {:else}
                        <span class="resource-pool-capacity" class:warn={pool.in_use >= pool.capacity}>
                          {pool.in_use} / {pool.capacity} in use
                        </span>
                      {/if}
                    </div>
                  </div>

                  <div class="resource-facts">
                    {#if pool.vram_budget_mb != null}
                      <div class="resource-fact">
                        <span class="resource-fact-label">VRAM budget</span>
                        <span class="resource-fact-val">{pool.vram_budget_mb.toLocaleString()} MB</span>
                      </div>
                    {/if}
                    {#if pool.active_model}
                      <div class="resource-fact">
                        <span class="resource-fact-label">Active model</span>
                        <span class="resource-fact-val">{pool.active_model}</span>
                      </div>
                    {/if}
                    {#if pool.resident_models.length > 0}
                      <div class="resource-fact">
                        <span class="resource-fact-label">Resident</span>
                        <span class="resource-fact-val">{pool.resident_models.join(", ")}</span>
                      </div>
                    {/if}
                    {#if pool.models.length > 0}
                      <div class="resource-fact">
                        <span class="resource-fact-label">Configured models</span>
                        <span class="resource-fact-val">{pool.models.join(", ")}</span>
                      </div>
                    {/if}
                  </div>

                  <div class="resource-section-title">Active leases</div>
                  {#if pool.leases.length === 0}
                    <div class="resource-empty">None right now</div>
                  {:else}
                    <table class="resource-table">
                      <thead>
                        <tr>
                          <th>Holder</th>
                          <th>Model</th>
                          <th>Priority</th>
                          <th>Held for</th>
                        </tr>
                      </thead>
                      <tbody>
                        {#each pool.leases as lease}
                          <tr>
                            <td>{lease.holder}</td>
                            <td>{lease.model ?? "—"}</td>
                            <td>
                              <span class="resource-priority-badge" class:interactive={lease.priority === "interactive"}>
                                {lease.priority}
                              </span>
                            </td>
                            <td>{lease.held_for_s}s</td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  {/if}

                  <div class="resource-section-title">Stats since server start</div>
                  <div class="resource-stats-grid">
                    <div class="resource-stat">
                      <span class="resource-stat-val ok">{pool.stats.granted}</span>
                      <span class="resource-stat-label">granted</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={pool.stats.denied_capacity > 0}>{pool.stats.denied_capacity}</span>
                      <span class="resource-stat-label">denied (full)</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={pool.stats.denied_model_busy > 0}>{pool.stats.denied_model_busy}</span>
                      <span class="resource-stat-label">denied (busy)</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={pool.stats.denied_vram_budget > 0}>{pool.stats.denied_vram_budget}</span>
                      <span class="resource-stat-label">denied (VRAM)</span>
                    </div>
                  </div>

                  <div class="resource-section-title">Since last refresh (~10s)</div>
                  <div class="resource-stats-grid">
                    <div class="resource-stat">
                      <span class="resource-stat-val ok">{recentResourceStats[name]?.granted ?? 0}</span>
                      <span class="resource-stat-label">granted</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={(recentResourceStats[name]?.denied_capacity ?? 0) > 0}>{recentResourceStats[name]?.denied_capacity ?? 0}</span>
                      <span class="resource-stat-label">denied (full)</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={(recentResourceStats[name]?.denied_model_busy ?? 0) > 0}>{recentResourceStats[name]?.denied_model_busy ?? 0}</span>
                      <span class="resource-stat-label">denied (busy)</span>
                    </div>
                    <div class="resource-stat">
                      <span class="resource-stat-val" class:warn={(recentResourceStats[name]?.denied_vram_budget ?? 0) > 0}>{recentResourceStats[name]?.denied_vram_budget ?? 0}</span>
                      <span class="resource-stat-label">denied (VRAM)</span>
                    </div>
                  </div>
                </div>
              {/each}
            {/if}
          </div>
        </div>
      {:else if showKgProgressPage}
        <div class="resources-page">
          <div class="node-toolbar">
            <span class="node-heading">Knowledge Graph</span>
          </div>
          <div class="resources-body">
            {#if !serverStatus?.knowledge_graph}
              <div class="empty-state"><p class="text-body">Knowledge graph status unavailable.</p></div>
            {:else}
              {@const kg = serverStatus.knowledge_graph}
              <div class="resource-card">
                <div class="resource-card-header">
                  <span class="resource-pool-name">Full sync</span>
                </div>
                <div class="resource-facts">
                  {#if (kg.sync_total ?? 0) > 0}
                    <div class="resource-fact">
                      <span class="resource-fact-label">Progress</span>
                      <span class="resource-fact-val">{kg.sync_done ?? 0} / {kg.sync_total}</span>
                    </div>
                  {:else}
                    <div class="resource-fact">
                      <span class="resource-fact-label">State</span>
                      <span class="resource-fact-val">{kg.state}</span>
                    </div>
                  {/if}
                  {#if kg.last_indexed}
                    <div class="resource-fact">
                      <span class="resource-fact-label">Last full sync completed</span>
                      <span class="resource-fact-val">{new Date(kg.last_indexed).toLocaleString()}</span>
                    </div>
                  {/if}
                </div>

                {#if kg.current_file}
                  <div class="resource-section-title">Now extracting</div>
                  <div class="resource-facts-stacked">
                    <div class="resource-fact">
                      <span class="resource-fact-label">File</span>
                      <span class="resource-fact-val">{kg.current_file}</span>
                    </div>
                    <div class="resource-fact">
                      <span class="resource-fact-label">Chunk</span>
                      <span class="resource-fact-val">{kg.current_file_chunks_done ?? 0} of {kg.current_file_chunks_total ?? 0}</span>
                    </div>
                  </div>
                {/if}

                <div class="resource-section-title">Chunk duration</div>
                <div class="resource-facts">
                  {#if kg.chunk_avg_duration_ms != null}
                    <div class="resource-fact">
                      <span class="resource-fact-label">Average (last {kg.chunk_duration_samples})</span>
                      <span class="resource-fact-val">{kg.chunk_avg_duration_ms.toFixed(0)}ms</span>
                    </div>
                    <div class="resource-fact">
                      <span class="resource-fact-label">Avg. Instructor retries</span>
                      <span class="resource-fact-val" class:warn={(kg.chunk_avg_retries ?? 0) > 0}>
                        {(kg.chunk_avg_retries ?? 0).toFixed(2)}
                      </span>
                    </div>
                    <div class="resource-fact">
                      <span class="resource-fact-label">Avg. size (tokens, est.)</span>
                      <span class="resource-fact-val">{(kg.chunk_avg_size_tokens ?? 0).toFixed(0)}</span>
                    </div>
                  {:else}
                    <div class="resource-empty">No chunks extracted yet</div>
                  {/if}
                </div>

                <div class="resource-section-title">Dropped chunks</div>
                <div class="resource-facts">
                  <div class="resource-fact">
                    <span class="resource-fact-label">Total (this session)</span>
                    <span class="resource-fact-val" class:warn={(kg.dropped_chunks_total ?? 0) > 0}>
                      {kg.dropped_chunks_total ?? 0}
                    </span>
                  </div>
                </div>
                {#if kg.dropped_chunks_recent && kg.dropped_chunks_recent.length > 0}
                  <table class="resource-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>File</th>
                        <th>Reason</th>
                        <th>Retries</th>
                        <th>Error</th>
                        <th>Dead letter file</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each kg.dropped_chunks_recent as d}
                        <tr>
                          <td>{new Date(d.time).toLocaleTimeString()}</td>
                          <td>{d.source_file}</td>
                          <td>{d.reason}</td>
                          <td>{d.retries}</td>
                          <td>{d.error}</td>
                          <td>{d.dead_letter_path ?? "—"}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}

                {#if kg.last_error}
                  <div class="resource-section-title">Last error</div>
                  <div class="resource-empty">{kg.last_error}</div>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {:else if showSettings}
        <div class="resources-page">
          <div class="node-toolbar">
            <span class="node-heading">Settings</span>
          </div>
          <div class="resources-body">
            <div class="resource-card">
              <div class="resource-card-header">
                <span class="resource-pool-name">Display scale</span>
              </div>
              <div class="scale-slider-row">
                <input type="range" min={SCALE_MIN} max={SCALE_MAX} step={SCALE_STEP} bind:value={cfg.scale} />
                <span class="scale-slider-value">{cfg.scale === DEFAULT_SCALE ? `${cfg.scale}× (default)` : `${cfg.scale}×`}</span>
              </div>
              <span class="setting-hint">Applied immediately — persisted across restarts.</span>
            </div>

            <div class="resource-card">
              <div class="resource-card-header">
                <span class="resource-pool-name">Chat instructions</span>
              </div>
              <textarea
                class="chat-system-prompt-input"
                rows="8"
                bind:value={chatSystemPrompt}
                disabled={chatSystemPromptLoading}
                placeholder="Standing instructions and preferences for the chat assistant — tone, language, things to always/never do…"
              ></textarea>
              <span class="setting-hint">
                Applies to every chat, every turn — this is the assistant's system prompt. It already has
                access to your notes, sources, past chats, and the knowledge graph, so it can pull in
                relevant material on its own; use this box for standing preferences (e.g. "always answer in
                Spanish") rather than one-off requests, which belong in the chat itself.
              </span>
              <button
                class="btn-primary"
                onclick={saveChatSystemPrompt}
                disabled={chatSystemPromptLoading || chatSystemPromptSaving}
              >
                {chatSystemPromptSaving ? "Saving…" : chatSystemPromptSaved ? "Saved" : "Save"}
              </button>
            </div>

            {#if isTauri}
              <div class="resource-card">
                <div class="resource-card-header">
                  <span class="resource-pool-name">Server</span>
                </div>
                <label class="setting-row">
                  <span class="setting-label">Hostname</span>
                  <input bind:value={cfg.hostname} placeholder="127.0.0.1" />
                </label>
                <label class="setting-row" style="flex-direction:row; align-items:center; gap:6px;">
                  <input type="checkbox" bind:checked={cfg.tls} style="width:auto" />
                  <span class="setting-label" style="margin:0">TLS / SSL (https)</span>
                </label>
                <div class="server-switcher" style="flex-direction:row; gap:8px;">
                  <label class="setting-row" style="flex:1">
                    <span class="setting-label">API port</span>
                    <input type="number" min="1" max="65535" bind:value={cfg.api_port} />
                  </label>
                  <label class="setting-row" style="flex:1">
                    <span class="setting-label">Web port</span>
                    <input type="number" min="1" max="65535" bind:value={cfg.web_port} />
                  </label>
                </div>
                <span class="setting-hint">Host/ports of the running <code>prisma serve</code> process — click Save to apply.</span>
              </div>

              <div class="resource-card">
                <div class="resource-card-header">
                  <span class="resource-pool-name">Vault sync</span>
                  <span class="resource-pool-capacity" class:warn={!syncStatus.running}>
                    {syncStatus.running ? "running" : "stopped"}
                  </span>
                </div>
                {#if syncStatus.running}
                  <div class="resource-facts">
                    <div class="resource-fact">
                      <span class="resource-fact-label">Local vault</span>
                      <span class="resource-fact-val">{syncStatus.vault_path}</span>
                    </div>
                    <div class="resource-fact">
                      <span class="resource-fact-label">Tracked files</span>
                      <span class="resource-fact-val">{syncStatus.tracked_files}</span>
                    </div>
                  </div>
                {:else if syncBlockedReason}
                  <div class="setting-hint setting-hint-error">{syncBlockedReason}</div>
                {:else}
                  <div class="setting-hint">Only runs when the hostname above isn't a loopback address (127.0.0.1/localhost) — syncing a local vault against the same machine is a no-op.</div>
                {/if}

                <label class="setting-row">
                  <span class="setting-label">Local vault folder</span>
                  <div class="server-switcher" style="flex-direction:row; align-items:center; gap:8px;">
                    <span class="server-switch-url">{cfg.vault_path ?? "(default location)"}</span>
                    <button class="btn-secondary" onclick={chooseVaultFolder}>Choose folder…</button>
                  </div>
                  <span class="setting-hint">Point this at your real vault (e.g. the same folder `prisma serve` uses locally) so syncing actually pushes/pulls your real notes — a fresh default folder starts out empty.</span>
                </label>

                {#if syncDiffLoading}
                  <div class="setting-hint">Comparing local vault vs. server…</div>
                {:else if syncDiffInfo}
                  {#if !syncDiffInfo.reachable}
                    <div class="setting-hint">Server unreachable — can't compare right now.</div>
                  {:else}
                    {@const total = syncDiffInfo.push_new + syncDiffInfo.pull_new + syncDiffInfo.push_delete + syncDiffInfo.pull_delete + syncDiffInfo.pull_update + syncDiffInfo.push_recreate}
                    {#if total === 0}
                      <div class="setting-hint">Local vault and server are in sync.</div>
                    {:else}
                      <div class="resource-facts-stacked">
                        {#if syncDiffInfo.push_new}<div class="resource-fact"><span class="resource-fact-label">New locally, not on server</span><span class="resource-fact-val">{syncDiffInfo.push_new}</span></div>{/if}
                        {#if syncDiffInfo.pull_new}<div class="resource-fact"><span class="resource-fact-label">New on server, not local</span><span class="resource-fact-val">{syncDiffInfo.pull_new}</span></div>{/if}
                        {#if syncDiffInfo.push_delete}<div class="resource-fact"><span class="resource-fact-label">Deleted locally, pending on server</span><span class="resource-fact-val">{syncDiffInfo.push_delete}</span></div>{/if}
                        {#if syncDiffInfo.pull_delete}<div class="resource-fact"><span class="resource-fact-label">Deleted on server, pending locally</span><span class="resource-fact-val">{syncDiffInfo.pull_delete}</span></div>{/if}
                        {#if syncDiffInfo.pull_update}<div class="resource-fact"><span class="resource-fact-label">Conflicting change (will pull newer)</span><span class="resource-fact-val">{syncDiffInfo.pull_update}</span></div>{/if}
                        {#if syncDiffInfo.push_recreate}<div class="resource-fact"><span class="resource-fact-label">Conflicting change (will re-push)</span><span class="resource-fact-val">{syncDiffInfo.push_recreate}</span></div>{/if}
                      </div>
                    {/if}
                  {/if}
                {/if}

                <div class="server-switcher" style="margin-top:8px">
                  <button class="btn-secondary" onclick={refreshSyncInfo}>Refresh</button>
                  {#if syncStatus.running}
                    <button class="btn-secondary" onclick={async () => { await syncStop(); await refreshSyncInfo(); }}>Stop</button>
                  {:else}
                    <button class="btn-secondary" onclick={async () => { syncBlockedReason = await syncStart(); await refreshSyncInfo(); }}>Start</button>
                  {/if}
                </div>
              </div>
            {/if}

            <div class="resource-card">
              <div class="resource-card-header">
                <span class="resource-pool-name">Reload server</span>
              </div>
              <div class="reload-scope">
                {#each [
                  { value: "all",    label: "All" },
                  { value: "api",    label: "API" },
                  { value: "web",    label: "Web (UI)" },
                  { value: "chroma", label: "Chroma" },
                  { value: "kg",     label: "Knowledge Graph" },
                ] as opt (opt.value)}
                  <label class="reload-option">
                    <input type="radio" name="reload-scope" value={opt.value} bind:group={reloadScope} />
                    {opt.label}
                  </label>
                {/each}
              </div>
              <button class="btn-danger" onclick={reloadServer} disabled={reloading}>
                {reloading ? "Reloading…" : "Reload"}
              </button>
            </div>

            <button class="btn-primary" onclick={saveAndApply}>Save</button>
          </div>
        </div>
      {:else}
        <div class="empty-state">
          <p class="text-body">Select a note or source from the sidebar.</p>
        </div>
      {/if}
    </main>

  </div>

  <!-- New stream form -->
  {#if showStreamForm}
  <button class="settings-backdrop" aria-label="Close" onclick={() => showStreamForm = false}></button>
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
  <button class="settings-backdrop" aria-label="Close" onclick={() => showDeepSearch = false}></button>
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
        bind:this={deepInputEl}
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
    {#if serverStatus?.knowledge_graph && serverStatus.knowledge_graph.state !== "idle"}
      <div class="deep-notice">
        {#if serverStatus.knowledge_graph.state === "indexing"}
          {#if serverStatus.knowledge_graph.last_indexed}
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

  <!-- Context menu -->
  {#if ctxMenu}
    <div class="ctx-overlay" role="button" tabindex="-1"
      onclick={() => { ctxMenu = null; ctxMovePicker = false; }}
      onkeydown={(e) => { if (e.key === "Escape") { ctxMenu = null; ctxMovePicker = false; } }}
    ></div>
    <div class="ctx-menu" style="left:{ctxMenu.x}px; top:{ctxMenu.y}px">
      {#if !ctxMovePicker}
        {#if ctxMenu.slug}
          {#if !ctxMenu.isChat}
            <button class="ctx-item" onclick={() => ctxMovePicker = true}>Move to…</button>
          {/if}
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
    <div class="ctx-overlay" role="button" tabindex="-1"
      onclick={() => renameTarget = null}
      onkeydown={(e) => { if (e.key === "Escape") renameTarget = null; }}
    ></div>
    <div class="rename-dialog">
      <div class="rename-label">Rename</div>
      <input class="rename-input" bind:this={renameInputEl} bind:value={renameTarget.value}
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
  /* Type scale: subtitles/body +25% over their un-emphasized 13px base —
     fine print (labels, hints, badges, buttons) and titles are untouched,
     keeping their original sizes throughout this file. */
  :global(.text-subtitle) { font-size: 16px; font-weight: 600; }
  :global(.text-body)     { font-size: 16px; font-weight: 400; }
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
    overflow: hidden;
  }

  /* Web-mode display scale (see applyWebScale) — deliberately scoped to
     :not(.tauri) and never applied in Tauri, which uses its own native
     window.set_zoom instead. .shell also contains this app's
     position:fixed overlays (context menu, settings panel, resize grips,
     status popover, etc.); a transform here makes it a new containing
     block for all of them, resolving their fixed offsets against
     .shell's own box instead of the true viewport — confirmed live
     2026-07-09 to misplace the CSD resize grips in Tauri specifically,
     where .shell also carries a 20px margin. Compensating width/height
     keeps the scaled box's rendered footprint exactly matching its
     unscaled parent instead of spilling past it. */
  :global(html:not(.tauri)) .shell {
    transform: scale(var(--ui-scale, 1));
    transform-origin: top left;
    width: calc(100% / var(--ui-scale, 1));
    height: calc(100vh / var(--ui-scale, 1));
  }


  .sidebar-search {
    flex-shrink: 0;
    padding: 10px 12px;
  }

  .search-wrap {
    width: 100%;
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

  .sidebar-footer {
    flex-shrink: 0;
    margin-top: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border-top: 1px solid #1a2d4a;
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
    border: none;
    padding: 0;
    background: transparent;
    cursor: default;
  }

  /* position: fixed, not absolute -- .status-anchor now lives inside
     .sidebar-footer, a descendant of .sidebar, which has overflow-x: hidden
     (for its tree/search content); an absolutely-positioned popover would
     get clipped to the sidebar's own bounds instead of floating over the
     rest of the window. */
  .status-popover {
    position: fixed;
    left: 12px;
    bottom: 46px;
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

  .sp-proc-row {
    display: flex;
    justify-content: space-between;
    padding: 2px 12px 2px 88px;
    font-size: 10px;
    font-family: "JetBrains Mono", monospace;
  }

  .sp-proc-name {
    color: #4a6a8a;
  }
  .sp-proc-name.bad {
    color: #f87171;
  }

  .sp-proc-mem {
    color: #1a3050;
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
    flex-shrink: 0;
    background: #080c16;
    border-right: 1px solid #1a2d4a;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .sidebar.collapsed { width: 0 !important; border-right: none; overflow: hidden; }

  .sidebar-resizer {
    width: 4px;
    flex-shrink: 0;
    cursor: col-resize;
    background: transparent;
  }
  .sidebar-resizer:hover, .sidebar-resizer.resizing { background: #2a5aaa; }

  .sidebar-collapse-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    flex-shrink: 0;
    background: #080c16;
    border: none;
    border-right: 1px solid #1a2d4a;
    color: #3d5470;
    cursor: pointer;
  }
  .sidebar-collapse-btn:hover { color: #6a9abb; background: #0d1829; }
  .sidebar-collapse-btn.collapsed { border-right: 1px solid #1a2d4a; }

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
  /* The sidebar itself scrolls as one column (see .sidebar's overflow-y)
     so individual sections don't need their own internal scroll area —
     without this, sections other than the vault tree had no scroll at
     all and just got silently clipped by the old .sidebar overflow:hidden
     once they had enough items to overflow. */
  .section-body { padding-bottom: 4px; }

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

  .tree-dir-icon { width: 1em; height: 1em; flex-shrink: 0; color: #3a5a7a; }

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
  .rendered :global(h2) { font-size: 21px; font-weight: 600; color: #c8ddf0; margin: 24px 0 10px; }
  .rendered :global(h3) { font-size: 18px; font-weight: 600; color: #a8c8e0; margin: 18px 0 8px; }
  .rendered :global(p)  { font-size: 16px; color: #9ab4c8; line-height: 1.7; margin-bottom: 12px; }
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

  /* ── Chat view ─────────────────────────────────────────────────────── */
  .chat-view {
    flex: 1;
    display: flex;
    flex-direction: row;
    overflow: hidden;
  }
  .chat-conversation {
    flex: 1 1 60%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .chat-notes-panel {
    flex: 0 0 340px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-left: 1px solid #1a2d4a;
    background: #080c16;
  }
  .chat-notes-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 18px;
    border-bottom: 1px solid #1a2d4a;
    flex-shrink: 0;
    min-height: 34px;
  }
  .chat-notes-title {
    font-size: 16px;
    font-weight: 600;
    color: #c8ddf0;
    flex: 1;
  }
  .chat-notes-regenerating {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: #facc15;
  }
  .chat-notes-regenerating .spin {
    animation: spin 1s linear infinite;
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  .chat-notes-count {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    color: #6a8aae;
    background: #0d1420;
    border: 1px solid #1a2d4a;
    padding: 1px 6px;
    border-radius: 10px;
  }
  .chat-notes-empty {
    color: #2a4060;
    font-size: 12px;
    text-align: center;
    padding: 14px 10px;
  }
  .chat-notes-summary {
    /* flex-grow:0 — this must hug its own content, not stretch to fill
       the panel. Forcing it to fill available height (flex-grow:1) was
       the actual bug behind "a lot of empty space": short summary text
       left a big dead gap between the text and the divider below it,
       regardless of any margin/line-height tweak on the text itself.
       Capped + scrollable so a *long* summary still doesn't push the
       pinned-turns list off-screen. */
    flex: 0 1 auto;
    max-height: 65%;
    min-height: 0;
    overflow-y: auto;
    padding: 8px 14px;
    border-bottom: 1px solid #1a2d4a;
  }
  .chat-notes-summary :global(.rendered) {
    /* .rendered's own base rule (padding: 28px 36px, flex: 1) is built for
       full-page note reading — applying it inside this ~300px sidebar was
       the actual "huge padding" bug, not anything on the outer container
       or on individual elements. This is the fix that was actually needed. */
    padding: 0;
    flex: initial;
    overflow-y: visible;
  }
  /* Tighter than the generic .rendered scale (built for full-width note
     pages) — this is a 340px sidebar, the default h1/h2 sizes and margins
     wasted a lot of it for no reason. */
  .chat-notes-summary :global(h1),
  .chat-notes-summary :global(h2),
  .chat-notes-summary :global(h3) {
    font-size: 12px;
    font-weight: 600;
    color: #c8ddf0;
    margin: 10px 0 4px;
  }
  .chat-notes-summary :global(h1:first-child),
  .chat-notes-summary :global(h2:first-child),
  .chat-notes-summary :global(h3:first-child) {
    margin-top: 0;
  }
  .chat-notes-summary :global(p) {
    color: #9ab4c8;
    font-size: 12px;
    line-height: 1.5;
    margin-bottom: 8px;
  }
  .chat-notes-summary :global(ul),
  .chat-notes-summary :global(ol) {
    /* list-style-position: inside (not the default "outside") so wrapped
       lines align flush with the marker instead of leaving a hanging-indent
       gap down the left side of every item — in a ~300px sidebar that gap
       reads as a lot of wasted empty margin. */
    list-style-position: inside;
    margin: 0 0 8px;
    padding: 0;
    font-size: 12px;
    color: #9ab4c8;
  }
  .chat-notes-summary :global(li) {
    margin-bottom: 4px;
    line-height: 1.4;
  }
  .chat-notes-summary :global(li p) {
    /* The renderer wraps list-item text in its own <p>, which otherwise
       stacks its 8px margin-bottom on top of <li>'s own spacing — most of
       what read as "huge margins" between list entries. */
    margin: 0;
    display: inline;
  }
  .chat-notes-summary :global(pre) {
    font-size: 11px;
    margin-bottom: 8px;
  }
  .chat-notes-pinned-list {
    /* Sized to its actual content (up to a cap), not a fixed share of the
       panel — with only 1-2 pinned turns this used to leave a lot of dead
       space below the list while starving the Summary above it.
       flex-shrink:0 so it can't be squeezed by the Summary's own flex-grow
       (that's what "cant even see the pinned turns" was — this list has to
       actually get the space its max-height reserves, not just be capped
       from growing past it). */
    flex: 0 0 auto;
    max-height: 40%;
    overflow-y: auto;
    padding: 8px 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .chat-notes-subheading {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #6a8aae;
    margin-bottom: 4px;
  }
  .pinned-turn-item {
    display: flex;
    align-items: baseline;
    gap: 6px;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-radius: 4px;
    padding: 5px 6px;
    cursor: pointer;
    color: #9ab4c8;
  }
  .pinned-turn-item:hover {
    background: #0d1420;
    color: #c8ddf0;
  }
  .pinned-turn-role {
    font-size: 10px;
    font-weight: 600;
    color: #6a8aae;
    flex-shrink: 0;
  }
  .pinned-turn-preview {
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chat-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 18px;
    background: #080c16;
    border-bottom: 1px solid #1a2d4a;
    flex-shrink: 0;
    min-height: 34px;
  }
  .chat-model {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    color: #c084fc;
    background: #1a0d2a;
    border: 1px solid #2a1a4a;
    padding: 2px 6px;
    border-radius: 3px;
  }
  .chat-context-usage {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    color: #6a8aae;
    background: #0d1420;
    border: 1px solid #1a2d4a;
    padding: 2px 6px;
    border-radius: 3px;
  }
  .chat-turns {
    flex: 1;
    overflow-y: auto;
    padding: 18px 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .chat-turn {
    max-width: 80%;
    padding: 10px 14px;
    border-radius: 8px;
    position: relative;
    transition: box-shadow 0.3s;
  }
  .chat-turn-flash {
    box-shadow: 0 0 0 2px #facc15;
  }
  /* User: handwritten feel — slanted, warmer accent, distinct from the system's own voice */
  .chat-turn-user {
    align-self: flex-end;
    background: #12203a;
    border: 1px solid #1a3a6a;
    font-style: italic;
  }
  /* Assistant: robot feel — monospace, cool purple accent matching the chat node-type color */
  .chat-turn-assistant {
    align-self: flex-start;
    background: #150d24;
    border: 1px solid #2a1a4a;
    font-family: "JetBrains Mono", monospace;
  }
  .chat-turn-pending {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 14px;
  }
  .chat-turn-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 4px;
  }
  .chat-turn-role {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #6a8aae;
  }
  .chat-turn-actions {
    display: flex;
    gap: 4px;
  }
  .chat-turn-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    cursor: pointer;
    color: #8aa8c8;
    padding: 3px 5px;
    border-radius: 3px;
    opacity: 0;
    transition: opacity 0.1s;
  }
  .chat-turn:hover .chat-turn-action {
    opacity: 0.7;
  }
  .chat-turn-action:hover {
    opacity: 1;
    background: #1a2d4a;
  }
  .chat-pin-toggle.pinned {
    /* Stays visible even when the turn isn't hovered — pinned state
       shouldn't be hidden by default, only the other hover-revealed
       actions (delete, unpinned pin) should be. */
    opacity: 1;
    color: #facc15;
    border: 1px solid #facc15;
  }
  .chat-turn-details-toggle {
    display: flex;
    align-items: center;
    gap: 4px;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    margin-bottom: 6px;
    font-size: 10px;
    color: #6a7a8f;
  }
  .chat-turn-details-toggle:hover { color: #93c5fd; }
  .chat-turn-details-arrow {
    display: inline-block;
    transition: transform 0.1s;
    font-size: 9px;
  }
  .chat-turn-details-arrow.expanded { transform: rotate(90deg); }
  .chat-turn-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 8px;
  }
  .chat-node-group {
    padding: 6px 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(139, 163, 192, 0.12);
  }
  .chat-node-group-heading {
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }
  .chat-node-group-toolcalls .chat-node-group-heading { color: #c084fc; }
  .chat-node-group-thoughts .chat-node-group-heading { color: #94a3b8; }
  .chat-node-group-recalls .chat-node-group-heading { color: #fbbf24; }
  .chat-node-group-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .node-box {
    padding: 4px 7px;
    border-radius: 4px;
    font-size: 10px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(139, 163, 192, 0.12);
  }
  .node-box-toolcall {
    font-family: "JetBrains Mono", monospace;
    color: #8a6ab0;
    border-color: rgba(192, 132, 252, 0.2);
  }
  .node-box-toolcall code { color: #c084fc; }
  .node-box-toolcall.node-box-error { color: #f87171; border-color: rgba(248, 113, 113, 0.3); }
  .node-box-toolcall-result {
    margin-top: 4px;
    padding-left: 8px;
    border-left: 2px solid rgba(192, 132, 252, 0.25);
    color: #a99bc4;
    font-family: inherit;
    white-space: pre-wrap;
    max-height: 120px;
    overflow-y: auto;
  }
  .node-box-thought {
    font-style: italic;
    color: #94a3b8;
    border-color: rgba(148, 163, 184, 0.2);
  }
  .node-box-recall {
    color: #d4a72c;
    border-color: rgba(251, 191, 36, 0.25);
  }
  .chat-turn-content {
    color: #c8ddf0;
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .chat-regen-model-picker {
    max-width: 130px;
    font-size: 10px;
    background: rgba(255, 255, 255, 0.03);
    color: #8ba3c0;
    border: 1px solid rgba(139, 163, 192, 0.2);
    border-radius: 4px;
    padding: 1px 3px;
  }
  .chat-media-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
  }
  .chat-media-jpg {
    max-width: 260px;
    max-height: 200px;
    border-radius: 6px;
    border: 1px solid rgba(139, 163, 192, 0.2);
  }
  .chat-media-pdf-link, .chat-media-slug {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(139, 163, 192, 0.2);
    color: #8ba3c0;
    font-size: 11px;
    text-decoration: none;
    cursor: pointer;
  }
  .chat-media-pdf-link:hover, .chat-media-slug:hover { color: #c8ddf0; }
  .chat-media-inline {
    padding: 6px 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(139, 163, 192, 0.2);
    max-width: 100%;
  }
  .chat-media-inline-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #6a7a8f;
    margin-bottom: 4px;
  }
  .chat-media-inline-code {
    margin: 0;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    color: #a99bc4;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 160px;
    overflow-y: auto;
  }
  .chat-turn-alternates {
    margin-top: 6px;
    font-size: 0.75rem;
    color: #7a8a9a;
  }
  .chat-turn-alternate-model {
    background: none;
    border: none;
    padding: 0 2px;
    cursor: pointer;
    font: inherit;
    color: #5c6b7a;
  }
  .chat-turn-alternate-model:hover { color: #93c5fd; }
  .chat-turn-alternate-model.active { color: #93c5fd; font-weight: 600; }
  .chat-turn-alternate-content {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px dashed rgba(139, 163, 192, 0.25);
    color: #9aafc4;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .chat-turn-alternate-content-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #6a7a8f;
    margin-bottom: 4px;
  }
  .claim-ref {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    vertical-align: super;
    font-size: 0.7em;
    color: #9ca3af;
    font-weight: 600;
    margin-left: 1px;
  }
  .claim-ref:hover { text-decoration: underline; }
  .claim-ref-citation { color: #9ca3af; }
  .claim-ref-attribution { color: #60a5fa; }
  .claim-ref-relational { color: #c084fc; }
  .claim-ref-inference { color: #6b7280; }
  .chat-claims {
    margin: 10px 0 0;
    padding: 8px 10px;
    border-radius: 8px;
    background: rgba(96, 165, 250, 0.05);
    border: 1px solid rgba(96, 165, 250, 0.18);
  }
  .chat-claims-heading {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #93c5fd;
    margin-bottom: 6px;
  }
  .chat-claims-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 11px;
    color: #8ba3c0;
  }
  .claim-box {
    padding: 6px 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(139, 163, 192, 0.15);
  }
  .claim-box-citation { border-color: rgba(156, 163, 175, 0.3); }
  .claim-box-attribution { border-color: rgba(96, 165, 250, 0.3); }
  .claim-box-relational { border-color: rgba(192, 132, 252, 0.3); }
  .claim-box-inference { border-color: rgba(107, 114, 128, 0.35); border-style: dashed; }
  .claim-index {
    display: inline-block;
    min-width: 14px;
    margin-right: 4px;
    font-weight: 600;
    color: #6a8aae;
  }
  .claim-relation {
    display: inline-block;
    margin-right: 6px;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }
  .claim-relation-citation {
    background: rgba(156, 163, 175, 0.15);
    color: #9ca3af;
  }
  .claim-relation-attribution {
    background: rgba(96, 165, 250, 0.15);
    color: #60a5fa;
  }
  .claim-relation-relational {
    background: rgba(192, 132, 252, 0.15);
    color: #c084fc;
  }
  .claim-relation-inference {
    background: rgba(107, 114, 128, 0.15);
    color: #6b7280;
  }
  .claim-faithfulness {
    margin-right: 6px;
    font-size: 10px;
  }
  .claim-faithfulness.faithful { color: #4ade80; }
  .claim-faithfulness.unfaithful { color: #f87171; }
  .claim-qualifier {
    display: inline-block;
    margin-right: 6px;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-style: italic;
    background: rgba(212, 167, 44, 0.12);
    color: #d4a72c;
  }
  .claim-rebuts {
    display: inline-block;
    margin-right: 6px;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    background: none;
    border: 1px solid rgba(248, 113, 113, 0.3);
    color: #f87171;
    cursor: pointer;
  }
  .claim-rebuts:hover { background: rgba(248, 113, 113, 0.1); }
  .claim-warrant {
    margin-top: 4px;
    padding: 4px 6px;
    border-left: 2px solid rgba(139, 163, 192, 0.25);
    font-size: 11px;
    color: #8ba3c0;
  }
  .claim-warrant-label {
    font-weight: 600;
    color: #6a8aae;
  }
  .claim-warrant-backing {
    color: #6a7a8f;
    font-size: 10px;
  }
  .claim-sources {
    margin-top: 3px;
  }
  .claim-source-link {
    background: none;
    border: none;
    padding: 0;
    color: #8ba3c0;
    text-decoration: underline dotted;
    cursor: pointer;
    font-size: 11px;
  }
  .claim-source-link:hover {
    color: #c8ddf0;
  }
  .claim-apa {
    margin-top: 2px;
    font-size: 10px;
    font-style: italic;
    color: #6a7a8f;
  }
  .chat-pending-attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px 18px 0;
    background: #080c16;
  }
  .chat-pending-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 4px 2px 8px;
    border-radius: 10px;
    background: rgba(74, 158, 255, 0.1);
    border: 1px solid rgba(74, 158, 255, 0.25);
    color: #8ba3c0;
    font-size: 11px;
  }
  .chat-pending-chip-remove {
    background: none;
    border: none;
    color: #6a7a8f;
    cursor: pointer;
    font-size: 13px;
    line-height: 1;
    padding: 0 3px;
  }
  .chat-pending-chip-remove:hover { color: #f87171; }
  .chat-attach-inline-form {
    padding: 8px 18px;
    background: #080c16;
    border-top: 1px solid #1a2d4a;
  }
  .chat-attach-inline-textarea {
    width: 100%;
    min-height: 70px;
    background: #0d1420;
    border: 1px solid #1a2d4a;
    border-radius: 6px;
    color: #c8ddf0;
    padding: 8px;
    font-size: 12px;
    font-family: "JetBrains Mono", monospace;
    resize: vertical;
  }
  .chat-attach-inline-actions {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
  .chat-attach-toolbar {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .chat-attach-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 8px;
    border-radius: 6px;
    background: none;
    border: 1px solid #1a2d4a;
    color: #8ba3c0;
    cursor: pointer;
    font-size: 11px;
  }
  .chat-attach-btn:hover { border-color: #4a9eff; color: #c8ddf0; }
  .chat-attach-slug-input {
    width: 90px;
    background: #0d1420;
    border: 1px solid #1a2d4a;
    border-radius: 6px;
    color: #c8ddf0;
    padding: 6px 8px;
    font-size: 11px;
  }
  .chat-attach-spinner { width: 12px; height: 12px; }
  .chat-input-row {
    display: flex;
    gap: 8px;
    padding: 12px 18px;
    background: #080c16;
    border-top: 1px solid #1a2d4a;
    flex-shrink: 0;
  }
  .chat-input {
    flex: 1;
    background: #0d1420;
    border: 1px solid #1a2d4a;
    border-radius: 6px;
    color: #c8ddf0;
    padding: 8px 12px;
    font-size: 13px;
    font-family: inherit;
  }
  .chat-input:focus {
    outline: none;
    border-color: #4a9eff;
  }
  .chat-send-btn {
    background: #1a3a6a;
    border: 1px solid #2a5aaa;
    color: #c8ddf0;
    padding: 8px 18px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
  }
  .chat-send-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .chat-send-btn:not(:disabled):hover {
    background: #2a5aaa;
  }
  /* ── Compute pools page ───────────────────────────────────────────────── */
  .resources-page {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .resources-body {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .resource-card {
    background: #0d1420;
    border: 1px solid #1a2d4a;
    border-radius: 10px;
    padding: 16px 20px;
  }
  .resource-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .resource-pool-icon {
    display: inline-flex;
    align-items: center;
    color: #4a9eff;
    margin-right: 8px;
  }
  .resource-pool-name {
    font-size: 15px;
    font-weight: 600;
    color: #e8edf8;
    font-family: "JetBrains Mono", monospace;
  }
  .resource-pool-capacity-group {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-end;
  }
  .resource-pool-capacity {
    font-size: 12px;
    color: #4ade80;
    background: #0d2a0d;
    border: 1px solid #1a4a1a;
    padding: 3px 10px;
    border-radius: 12px;
  }
  .resource-pool-capacity.warn {
    color: #facc15;
    background: #1a1a0d;
    border-color: #3a3010;
  }
  .resource-facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px 24px;
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #1a2d4a;
  }
  .resource-facts-stacked {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #1a2d4a;
  }
  .resource-fact {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .resource-fact-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #6a8aae;
  }
  .resource-fact-val {
    font-size: 13px;
    color: #c8ddf0;
    font-family: "JetBrains Mono", monospace;
    overflow-wrap: break-word;
  }
  .resource-fact-val.warn {
    color: #f59e0b;
  }
  .resource-section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #6a8aae;
    margin: 14px 0 8px;
  }
  .resource-empty {
    font-size: 12px;
    color: #2a4060;
  }
  .resource-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .resource-table th {
    text-align: left;
    color: #6a8aae;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 4px 10px 6px 0;
    border-bottom: 1px solid #1a2d4a;
  }
  .resource-table td {
    padding: 6px 10px 6px 0;
    color: #c8ddf0;
    font-family: "JetBrains Mono", monospace;
    border-bottom: 1px solid #10192a;
    overflow-wrap: break-word;
  }
  .resource-priority-badge {
    font-size: 10px;
    text-transform: uppercase;
    padding: 2px 7px;
    border-radius: 3px;
    background: #1a2d4a;
    color: #8aa8c8;
  }
  .resource-priority-badge.interactive {
    background: #1a0d2a;
    color: #c084fc;
  }
  .resource-stats-grid {
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
  }
  .resource-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    min-width: 70px;
  }
  .resource-stat-val {
    font-size: 20px;
    font-weight: 600;
    font-family: "JetBrains Mono", monospace;
    color: #4ade80;
  }
  .resource-stat-val.warn {
    color: #facc15;
  }
  .resource-stat-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #6a8aae;
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
    border: none;
    padding: 0;
    cursor: default;
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

  .server-switcher {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 10px;
  }
  .server-switch-url { font-size: 11px; color: #6a8aa8; }

  .scale-slider-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .scale-slider-row input[type="range"] {
    flex: 1;
    width: auto;
    padding: 0;
    background: none;
    border: none;
    accent-color: #4a9eff;
  }
  .scale-slider-value {
    font-size: 12px;
    color: #e8edf8;
    min-width: 84px;
    text-align: right;
    flex-shrink: 0;
  }

  .chat-system-prompt-input {
    width: 100%;
    padding: 10px 12px;
    background: #0d1320;
    border: 1px solid #1a2d4a;
    border-radius: 5px;
    color: #e8edf8;
    font-size: 12px;
    font-family: inherit;
    line-height: 1.5;
    resize: vertical;
    outline: none;
    margin-bottom: 8px;
  }
  .chat-system-prompt-input:focus { border-color: #4a9eff; }
  .chat-system-prompt-input:disabled { opacity: 0.6; }

  .setting-hint {
    font-size: 10px;
    color: #2a4060;
    line-height: 1.5;
  }
  .setting-hint-error { color: #f87171; }
  .chat-system-prompt-input + .setting-hint {
    display: block;
    margin-bottom: 10px;
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
  .reload-scope {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  .reload-option {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: #8a9bb0;
    cursor: pointer;
    user-select: none;
  }
  .reload-option input[type="radio"] { accent-color: #4a90d9; cursor: pointer; }

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
