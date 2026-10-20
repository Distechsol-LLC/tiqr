import ChartColumn from '@lucide/svelte/icons/chart-column';
import Ticket from '@lucide/svelte/icons/ticket';
import UsersRound from '@lucide/svelte/icons/users-round';
import type { Component } from 'svelte';

import type { AppPath } from '@/router.ts';
import type { Role } from '$/auth.ts';

type NavItem = {
  icon: Component;
  label: string;
  path: AppPath;
};

// Mirrors the permission matrix in apps/core/src/tiqr/core/service.py: everyone works tickets,
// admins manage accounts, managers only read them to pick assignees, and staff see operations
const NAV: Record<Role, NavItem[]> = {
  admin: [
    { icon: Ticket, label: 'Tickets', path: '/admin' },
    { icon: UsersRound, label: 'Users', path: '/admin/users' },
    { icon: ChartColumn, label: 'Overview', path: '/admin/overview' },
  ],
  manager: [
    { icon: Ticket, label: 'Tickets', path: '/manager' },
    { icon: UsersRound, label: 'Accounts', path: '/manager/accounts' },
    { icon: ChartColumn, label: 'Overview', path: '/manager/overview' },
  ],
  operator: [{ icon: Ticket, label: 'Tickets', path: '/operator' }],
};

export { NAV };
