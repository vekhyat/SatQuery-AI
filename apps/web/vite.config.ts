import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } }, // Pair with apps/web/server.py --port 8000, not API-only Uvicorn.
  preview: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } },
});
