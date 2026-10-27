import { mount } from 'svelte';

import App from '@/App.svelte';
import { ERROR_SERVICE_WORKER } from '@/config/errors.ts';
import { branding } from '%/useBranding.svelte.ts';
import { i18n } from '%/useLocale.svelte.ts';
import { theme } from '%/useTheme.svelte.ts';

const target = document.getElementById('root');

// The install's name, theme and languages come first, so nothing flashes in the built-in ones
const start = async (): Promise<void> => {
  await branding.load();
  theme.configure(branding.theme);
  i18n.configure(branding.locales);
  document.title = branding.appName;

  if (branding.logoSrc)
    document.querySelector('link[rel=icon]')?.setAttribute('href', branding.logoSrc);
  if (target) mount(App, { target });
};

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

// Copyright Notice
console.log('© 2026 Distechsol LLC');

registerSW();
void start();
