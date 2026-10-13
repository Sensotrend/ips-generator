/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import { workboxOptions } from './src/pwa/workbox.ts'

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
      // App shell only; /api/ is NetworkOnly (PHI rule). See src/pwa/workbox.ts.
      workbox: workboxOptions,
    }),
  ],
  server: {
    proxy: {
      // The API (uvicorn). Override with VITE_API_PROXY, e.g. http://localhost:8010.
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: false,
  },
})
