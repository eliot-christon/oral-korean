import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Never inline a font as a base64 `data:` URI. Vite inlines every asset under 4 KB,
    // which puts each small Jua or Nunito slice, and its woff fallback that no supported
    // browser loads, into the render-blocking stylesheet: 82 KB that gzip cannot shrink.
    // As files, the browser fetches only the slices a page actually shows.
    assetsInlineLimit: (filePath) => (/\.woff2?$/.test(filePath) ? false : undefined),
  },
  server: {
    proxy: {
      // Must match the backend's default host/port in `src/oral_korean/config.py`.
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
  },
})
