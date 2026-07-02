import { defineConfig } from "vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { SvelteKitPWA } from "@vite-pwa/sveltekit";
import fs from "fs";
import path from "path";

function findSvelteFiles(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...findSvelteFiles(full));
    else if (entry.name.endsWith(".svelte")) results.push(full);
  }
  return results;
}

// vite-plugin-svelte has a race on startup: if a virtual CSS module is requested
// before the parent .svelte is compiled, it returns undefined and Vite serves the
// raw .svelte file as CSS, breaking PostCSS. Pre-warming all .svelte files on
// server start ensures the cache is populated before any CSS request arrives.
const svelteCssCacheMissGuard = {
  name: "svelte-css-cache-miss-guard",
  enforce: "pre",
  configureServer(server) {
    server.httpServer?.once("listening", async () => {
      const files = findSvelteFiles(path.join(server.config.root, "src"));
      await Promise.all(files.map((f) => server.transformRequest(f).catch(() => {})));
    });
  },
  transform(code, id) {
    if (id.includes("?svelte&type=style") && code.trimStart().startsWith("<")) {
      return { code: "", map: null };
    }
  },
};

export default defineConfig({
  plugins: [
    sveltekit(),
    svelteCssCacheMissGuard,
    SvelteKitPWA({
      registerType: "autoUpdate",
      scope: "/app/",
      base: "/app/",
      injectRegister: false,  // registered manually in +layout.svelte via virtual:pwa-register
      kit: {
        spa: true,  // adapter-static SPA mode (fallback: index.html)
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2}"],
        // Explicitly undefined (not omitted): @vite-pwa/sveltekit auto-injects
        // a default navigateFallback whenever the key is absent from this
        // object, regardless of its value — the key merely needs to be
        // *present* to suppress that. With ssr:false + adapter-static, the
        // SPA fallback page is synthesized in a build phase that runs after
        // this plugin's precache scan, so there's never a real artifact to
        // bind an offline-navigation route to (produces a runtime
        // "non-precached-url" error regardless of the URL configured). Also
        // of no real value here: Prisma requires a live local/LAN server to
        // do anything, so a cached shell with no backend isn't a capability
        // worth having. Online navigation is unaffected — the browser just
        // fetches fresh HTML normally.
        navigateFallback: undefined,
      },
      manifest: {
        name: "Prisma",
        short_name: "Prisma",
        description: "Research workspace with semantic search over your papers and notes",
        theme_color: "#1a1a2e",
        background_color: "#1a1a2e",
        display: "standalone",
        scope: "/app/",
        start_url: "/app/",
        icons: [
          { src: "/app/pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "/app/pwa-512x512.png", sizes: "512x512", type: "image/png" },
          { src: "/app/pwa-maskable-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
        screenshots: [
          {
            src: "/app/screenshots/desktop-wide.png",
            sizes: "1280x800",
            type: "image/png",
            form_factor: "wide",
            label: "Prisma vault dashboard on desktop",
          },
          {
            src: "/app/screenshots/mobile-narrow.png",
            sizes: "390x844",
            type: "image/png",
            form_factor: "narrow",
            label: "Prisma vault dashboard on mobile",
          },
        ],
      },
    }),
  ],
});
