import { type Hooks, type Navigation, type Path, createRouter } from 'sv-router';

import Dashboard from '@/layouts/Dashboard.svelte';
import License from '@/pages/License.svelte';
import Login from '@/pages/Login.svelte';
import NotFound from '@/pages/NotFound.svelte';
import Overview from '@/pages/Overview.svelte';
import Tickets from '@/pages/Tickets.svelte';
import TicketTypes from '@/pages/TicketTypes.svelte';
import Users from '@/pages/Users.svelte';
import VisitorTypes from '@/pages/VisitorTypes.svelte';
import { auth } from '%/useAuth.svelte.ts';
import type { Role } from '$/auth.ts';

// sv-router takes the base without slashes; vite.config.mts sets it to '/tiqr/'
const BASE = import.meta.env.BASE_URL.replaceAll('/', '');

// Where a signed-in user lands, or sign-in for everyone else; sv-router redirects by throwing navigate()
const redirectHome = (): Promise<Navigation> =>
  navigate(auth.session ? `/${auth.session.user.role}` : '/login', { replace: true });

const toHome: Hooks = {
  beforeLoad: async (): Promise<void> => {
    await auth.restore();

    throw redirectHome();
  },
};

const signedOut: Hooks = {
  beforeLoad: async (): Promise<void> => {
    await auth.restore();

    if (auth.session) throw redirectHome();
  },
};

// Each role has its own area; the API still decides every action, this only picks the screens
const roleArea = (role: Role): Hooks => ({
  beforeLoad: async (): Promise<void> => {
    await auth.restore();

    if (auth.session?.user.role !== role) throw redirectHome();
  },
});

const routes = {
  '*notfound': NotFound,
  '/': {
    // Never shown: the hook always redirects
    '/': NotFound,
    hooks: toHome,
  },
  '/admin': {
    '/': Tickets,
    '/license': License,
    '/overview': Overview,
    '/ticket-types': TicketTypes,
    '/users': Users,
    '/visitor-types': VisitorTypes,
    hooks: roleArea('admin'),
    layout: Dashboard,
  },
  '/login': {
    '/': Login,
    hooks: signedOut,
  },
  '/manager': {
    '/': Tickets,
    '/accounts': Users,
    '/overview': Overview,
    '/ticket-types': TicketTypes,
    '/visitor-types': VisitorTypes,
    hooks: roleArea('manager'),
    layout: Dashboard,
  },
  '/operator': {
    '/': Tickets,
    hooks: roleArea('operator'),
    layout: Dashboard,
  },
};

type AppPath = Path<typeof routes>;

export type { AppPath };
export const { isActive, navigate, p } = createRouter(routes, { base: BASE });
