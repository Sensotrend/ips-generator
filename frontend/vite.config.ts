/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'IPS Generator',
        short_name: 'IPS Gen',
        description: 'Generate International Patient Summaries from healthcare documents',
        theme_color: '#1d4e89',
        background_color: '#ffffff',
        display: 'standalone',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        // Precache the app shell only (built JS/CSS/HTML/icons).
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        // Never serve the SPA shell for API calls.
        navigateFallbackDenylist: [/^\/api\//],
        // runtimeCaching: CLAUDE.md forbids caching PHI in the service worker. API responses
        // may contain PHI, so /api/ is explicitly NetworkOnly. Do not add other runtime caches
        // for anything that can carry patient data.
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: false,
  },
})
