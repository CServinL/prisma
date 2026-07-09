// Tauri doesn't have a Node.js server to do proper SSR
// so we use adapter-static with a fallback to index.html to put the site in SPA mode
// See: https://svelte.dev/docs/kit/single-page-apps
// See: https://v2.tauri.app/start/frontend/sveltekit/ for more info
import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      fallback: "index.html",
      // Built into a staging directory, then atomically swapped into place by
      // scripts/swap-build.mjs — building straight into "build" would leave
      // prisma serve's web process (which mounts "build" live via
      // CleanUrlStaticFiles) serving 404s for the several seconds the old
      // output is deleted before the new one finishes writing.
      pages: "build-next",
      assets: "build-next",
    }),
    paths: {
      base: "/app",
    },
  },
};

export default config;
