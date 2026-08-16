import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API is same-origin in production (one container serves both), so only the dev server needs
// a proxy. Build output goes straight into the backend package so the Docker image is one COPY.
export default defineConfig({
  plugins: [react()],
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
