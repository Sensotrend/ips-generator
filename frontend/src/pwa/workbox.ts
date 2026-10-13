// Workbox (service worker) options, shared by vite.config.ts and the tests.
//
// PHI rule (CLAUDE.md, PLAN D8): the service worker precaches the app shell only. API responses
// can contain patient data, so everything under /api/ is NetworkOnly and is never served from
// the SPA fallback. Do NOT add runtime caches for anything that can carry patient data.
// `npm run build` asserts this on the generated sw.js (scripts/check-sw.mjs).

export const API_PREFIX = '/api/'

export const isApiRequest = ({ url }: { url: URL }): boolean => url.pathname.startsWith('/api/')

export const workboxOptions = {
  // App shell only: built JS/CSS/HTML/icons (and the pdf.js worker module).
  globPatterns: ['**/*.{js,mjs,css,html,svg,png,ico,webmanifest}'],
  // The pdf.js worker is ~1 MB; it is code, not data.
  maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
  navigateFallbackDenylist: [/^\/api\//],
  runtimeCaching: [
    {
      urlPattern: isApiRequest,
      handler: 'NetworkOnly' as const,
    },
  ],
}
