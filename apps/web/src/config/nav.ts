import ChartColumn from '@lucide/svelte/icons/chart-column';
import IdCard from '@lucide/svelte/icons/id-card';
import KeyRound from '@lucide/svelte/icons/key-round';
import Percent from '@lucide/svelte/icons/percent';
import Plug from '@lucide/svelte/icons/plug';
import Settings from '@lucide/svelte/icons/settings';
import Tag from '@lucide/svelte/icons/tag';
import Ticket from '@lucide/svelte/icons/ticket';
import UsersRound from '@lucide/svelte/icons/users-round';
import type { Component } from 'svelte';

import type { Messages } from '@/locales/en.ts';
import type { AppPath } from '@/router.ts';
import type { Role } from '$/auth.ts';
import type { Mode } from '$/settings.ts';

type NavItem = {
  // Shown in the badge mode instead of icon, when it differs
  badgeIcon?: Component;
  icon: Component;
  // Looked up in the showing language when rendered
  label: keyof Messages['nav'];
  // Only shown in these modes; every mode when left out
  modes?: Mode[];
  path: AppPath;
};

// Mirrors the permission matrix in apps/core/src/tiqr/core/service.py: everyone works tickets,
// admins manage accounts, managers read them to pick assignees and manage operators, and staff
// see operations and set ticket prices and visitor discounts. Badges have no prices, so no ticket types
const NAV: Record<Role, NavItem[]> = {
  admin: [
    { badgeIcon: IdCard, icon: Ticket, label: 'tickets', path: '/admin' },
    {
      icon: Tag,
      label: 'ticketTypes',
      modes: ['ticket'],
      path: '/admin/ticket-types',
    },
    { icon: Percent, label: 'visitorTypes', path: '/admin/visitor-types' },
    { icon: ChartColumn, label: 'overview', path: '/admin/overview' },
    { icon: UsersRound, label: 'users', path: '/admin/users' },
    { icon: Plug, label: 'biostar', path: '/admin/biostar' },
    { icon: KeyRound, label: 'license', path: '/admin/license' },
    { icon: Settings, label: 'settings', path: '/admin/settings' },
  ],
  manager: [
    { badgeIcon: IdCard, icon: Ticket, label: 'tickets', path: '/manager' },
    {
      icon: Tag,
      label: 'ticketTypes',
      modes: ['ticket'],
      path: '/manager/ticket-types',
    },
    { icon: Percent, label: 'visitorTypes', path: '/manager/visitor-types' },
    { icon: ChartColumn, label: 'overview', path: '/manager/overview' },
    { icon: UsersRound, label: 'users', path: '/manager/users' },
  ],
  operator: [{ badgeIcon: IdCard, icon: Ticket, label: 'tickets', path: '/operator' }],
};

export { NAV };
