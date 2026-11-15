import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser talks only to this origin; /api/* is forwarded to FastAPI (so the session cookie is same-origin).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.API_URL || 'http://localhost:8000', changeOrigin: true, ws: true, xfwd: true,
                rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
