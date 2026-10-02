import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// The repo root, so the frontend reads the same .env file as the backend.
const repoRoot = fileURLToPath(new URL('..', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  envDir: repoRoot,
  server: {
    port: 5173,
    // Forward API calls to the FastAPI dev server so the browser never has to
    // deal with CORS locally. Feature routers will be mounted under /api.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
