import { defineConfig } from 'vite'

// Library build + unit tests. The demo harness has its own config (vite.demo.config.js).
export default defineConfig({
  build: {
    lib: { entry: 'src/index.js', formats: ['es'], fileName: 'index' },
    // Peers and runtime dependencies stay external: the host's bundler resolves them once.
    rollupOptions: { external: [
        /^react(-dom|-markdown)?(\/|$)/,
        /^remark-gfm(\/|$)/,
        /^ajv(\/|$)/,
        // CodeMirror is a peer: two copies of @codemirror/state or view break instanceof checks.
        /^@codemirror\//,
        /^@lezer\//,
      ],
    },
  },
  test: {
    environment: 'node',
    // ajv compiles ~60 schemas and jsdom renders the corpus: slow on a shared, loaded machine.
    testTimeout: 30000,
    include: ['test/**/*.test.{js,jsx}', 'src/**/*.test.{js,jsx}'],
  },
})
