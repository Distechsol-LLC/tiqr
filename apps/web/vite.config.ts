import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  build: {
    // `apps/api` copies this folder into the package at release time
    outDir: 'build',
    sourcemap: false,
  },
  server: {
    proxy: {
      // Leave `changeOrigin` off so the API's origin check sees the browser's own host
      '/api': 'http://127.0.0.1:7102',
    },
  },
})
