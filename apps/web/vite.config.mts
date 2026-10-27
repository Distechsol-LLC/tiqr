import { type Connect, defineConfig, type Plugin, type PluginOption } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { VitePWA } from 'vite-plugin-pwa';

const BASE = '/tiqr/';
const BASE_WITHOUT_SLASH = BASE.slice(0, -1);

// sv-router writes the home route as '/tiqr', which the API serves but Vite would 404
const serveBaseWithoutSlash = (): Plugin => {
  const rewrite: Connect.NextHandleFunction = (req, _res, next) => {
    if (req.url === BASE_WITHOUT_SLASH || req.url?.startsWith(`${BASE_WITHOUT_SLASH}?`))
      req.url = req.url.replace(BASE_WITHOUT_SLASH, BASE);
    next();
  };

  return {
    configurePreviewServer: (server) => {
      server.middlewares.use(rewrite);
    },
    configureServer: (server) => {
      server.middlewares.use(rewrite);
    },
    name: 'serve-base-without-slash',
  };
};

// https://vite.dev/config
export default defineConfig({
  base: BASE,
  resolve: {
    alias: {
      '@': '/src',
      '$': '/src/data',
      '%': '/src/utils',
      '#': '/src/assets',
    },
  },
  plugins: [
    serveBaseWithoutSlash(),
    tailwindcss(),
    svelte({
      inspector: true,
    }),
    VitePWA({
      filename: 'sw.ts',
      injectManifest: {
        globPatterns: ['**/*.{html,css,js,png,webp,ttf,woff2}'],
      },
      injectRegister: null,
      manifest: false,
      registerType: 'autoUpdate',
      srcDir: 'src',
      strategies: 'injectManifest',
    }),
  ] as PluginOption[],
  build: {
    outDir: 'build',
    sourcemap: false,
  },
  server: {
    proxy: {
      // Keeps the browser's Host, so the API's same-origin check on writes matches Origin
      '/api': { changeOrigin: false, target: 'http://127.0.0.1:7102' },
    },
  },
})
