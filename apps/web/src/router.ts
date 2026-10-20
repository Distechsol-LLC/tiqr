import { type Hooks, createRouter } from 'sv-router';

import Home from '@/pages/Home.svelte';
import Login from '@/pages/Login.svelte';
import NotFound from '@/pages/NotFound.svelte';
import { auth } from '%/useAuth.svelte.ts';

// sv-router takes the base without slashes; vite.config.mts sets it to '/tiqr/'
const BASE = import.meta.env.BASE_URL.replaceAll('/', '');

// Redirects anyone whose sign-in state doesn't match the route
const guard = (isSignedIn: boolean): Hooks => ({
  beforeLoad: async (): Promise<void> => {
    await auth.restore();

    // sv-router redirects by throwing navigate()
    if (Boolean(auth.session) !== isSignedIn)
      throw navigate(isSignedIn ? '/login' : '/', { replace: true });
  },
});

export const { navigate, p } = createRouter(
  {
    '*notfound': NotFound,
    '/': {
      '/': Home,
      hooks: guard(true),
    },
    '/login': {
      '/': Login,
      hooks: guard(false),
    },
  },
  { base: BASE }
);
