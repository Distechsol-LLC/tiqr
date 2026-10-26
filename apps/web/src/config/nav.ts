import ChartColumn from '@lucide/svelte/icons/chart-column';
import KeyRound from '@lucide/svelte/icons/key-round';
import Percent from '@lucide/svelte/icons/percent';
import Tag from '@lucide/svelte/icons/tag';
import Ticket from '@lucide/svelte/icons/ticket';
import UsersRound from '@lucide/svelte/icons/users-round';
import type { Component } from 'svelte';

import type { Messages } from '@/locales/en.ts';
import type { AppPath } from '@/router.ts';
import type { Role } from '$/auth.ts';

type NavItem = {
  icon: Component;
  // Looked up in the showing language when rendered
  label: keyof Messages['nav'];
  path: AppPath;
};

// Mirrors the permission matrix in apps/core/src/tiqr/core/service.py: everyone works tickets,
// admins manage accounts, managers read them to pick assignees and manage operators, and staff
// see operations and set ticket prices and visitor discounts
const NAV: Record<Role, NavItem[]> = {
  admin: [
    { icon: Ticket, label: 'tickets', path: '/admin' },
    { icon: Tag, label: 'ticketTypes', path: '/admin/ticket-types' },
    { icon: Percent, label: 'visitorTypes', path: '/admin/visitor-types' },
    { icon: ChartColumn, label: 'overview', path: '/admin/overview' },
    { icon: UsersRound, label: 'users', path: '/admin/users' },
    { icon: KeyRound, label: 'license', path: '/admin/license' },
  ],
  manager: [
    { icon: Ticket, label: 'tickets', path: '/manager' },
    { icon: UsersRound, label: 'accounts', path: '/manager/accounts' },
    { icon: Tag, label: 'ticketTypes', path: '/manager/ticket-types' },
    { icon: Percent, label: 'visitorTypes', path: '/manager/visitor-types' },
    { icon: ChartColumn, label: 'overview', path: '/manager/overview' },
  ],
  operator: [{ icon: Ticket, label: 'tickets', path: '/operator' }],
};

export { NAV };
