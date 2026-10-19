import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { VitePWA } from 'vite-plugin-pwa';

// https://vite.dev/config
export default defineConfig({
  base: '/tiqr/',
  resolve: {
    alias: {
      '@': '/src',
      '$': '/src/data',
      '%': '/src/utils',
      '#': '/src/assets',
    },
  },
  plugins: [
    tailwindcss(),
    svelte({
      inspector: true,
    }),
    VitePWA({
      filename: 'sw.ts',
      injectManifest: {
        globPatterns: ['**/*.{html,css,js,png,webp,ttf,woff2,webmanifest}'],
      },
      injectRegister: null,
      manifest: false,
      registerType: 'autoUpdate',
      srcDir: 'src',
      strategies: 'injectManifest',
    }),
  ],
  build: {
    outDir: 'build',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:7102',
    },
  },
})
