import { mount } from 'svelte';

import App from '@/App.svelte';
import { ERROR_SERVICE_WORKER } from '@/config/errors.ts';

const target = document.getElementById('root');

if (target) mount(App, { target });

const registerSW = (): void => {
  if ('serviceWorker' in navigator)
    window.addEventListener('load', () => {
      navigator.serviceWorker
        .register('/tiqr/sw.js', {
          scope: '/tiqr/',
        })
        .catch((error: unknown) => {
          if (error instanceof Error) console.error(ERROR_SERVICE_WORKER, error);
        });
    });
};

registerSW();
