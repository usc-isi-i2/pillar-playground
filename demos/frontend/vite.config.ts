import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  preview: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: {
    // The CSS minifier reorders declarations: it moved `font-variant-numeric` above the `font`
    // shorthand in replan.css, which then reset it. The stylesheets are small; ship them as written.
    cssMinify: false,
    rollupOptions: {
      input: {
        index: resolve(import.meta.dirname, 'index.html'),
        copilot: resolve(import.meta.dirname, 'copilot.html'),
        replan: resolve(import.meta.dirname, 'replan.html'),
      },
    },
  },
});
