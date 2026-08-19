import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// The API is same-origin in production (one container serves both), so only the dev server needs
// a proxy. Build output goes straight into the backend package so the Docker image is one COPY.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // `sw-src/sw.js` keeps its own hand-written push-notification handlers; injectManifest is
      // the strategy that lets Workbox generate the precache list without also generating (and
      // so overwriting) the rest of the worker the way `generateSW` would.
      strategies: 'injectManifest',
      srcDir: 'sw-src',
      filename: 'sw.js',
      // public/manifest.webmanifest stays the one hand-edited source — `manifest: false` stops
      // the plugin from also trying to own manifest generation.
      manifest: false,
      // main.tsx registers the worker itself (see the eager `serviceWorker.register` call there).
      injectRegister: false,
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}', 'tesseract/**/*'],
        // The tesseract WASM core + traineddata exceed Workbox's default 2 MB precache cap.
        maximumFileSizeToCacheInBytes: 15 * 1024 * 1024,
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.BRICKSEEKER_API ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../backend/app/static',
    emptyOutDir: true,
    sourcemap: false,
  },
})
