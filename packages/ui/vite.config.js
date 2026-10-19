import { defineConfig } from 'vite'

// Library build + unit tests. The demo harness has its own config (vite.demo.config.js).
export default defineConfig({
  build: {
    lib: { entry: 'src/index.js', formats: ['es'], fileName: 'index' },
    rollupOptions: { external: ['react', 'react-dom', /^react\//] },
  },
  test: {
    environment: 'node',
    include: ['test/**/*.test.js', 'src/**/*.test.js'],
  },
})
