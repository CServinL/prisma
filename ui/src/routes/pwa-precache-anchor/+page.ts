// Overrides the root layout's ssr=false so this one route can be prerendered.
// Its only purpose is to make `.svelte-kit/output/prerendered/` exist, so
// @vite-pwa/sveltekit's unconditional `prerendered/**/*.{html,json}` glob
// (which it appends regardless of SPA mode) matches at least one real file
// instead of warning about zero matches on every build.
export const ssr = true;
export const prerender = true;
