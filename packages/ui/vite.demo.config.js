import { defineConfig } from 'vite'

// Demo harness (see demo/README.md): the page Playwright + axe drive.
export default defineConfig({
  root: 'demo',
  server: { host: '127.0.0.1', port: 4173, strictPort: true },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
})
