<script lang="ts">
  import PanelLeftClose from '@lucide/svelte/icons/panel-left-close';
  import PanelLeftOpen from '@lucide/svelte/icons/panel-left-open';
  import { tick } from 'svelte';

  import AccountMenu from '@/components/AccountMenu.svelte';
  import Logo from '@/components/Logo.svelte';
  import { NAV } from '@/config/nav.ts';
  import { isActive, p } from '@/router.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { branding } from '%/useBranding.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { sidebar } from '%/useSidebar.svelte.ts';

  const ICON_SIZE = 18;

  let collapseButton = $state<HTMLButtonElement>();
  let expandButton = $state<HTMLButtonElement>();

  const user = $derived(auth.session?.user);
  const items = $derived(user ? NAV[user.role] : []);

  // The pressed button leaves with the state it belongs to, so a keyboard user's focus moves to
  // its counterpart. Not after a click (detail > 0): focusing would pop that button's tooltip
  const toggle = async ({ detail }: MouseEvent): Promise<void> => {
    sidebar.toggle();
    if (detail > 0) return;
    await tick();
    (sidebar.isCollapsed ? expandButton : collapseButton)?.focus();
  };
</script>

<!-- Only the width animates: everything inside keeps its place and the overflow is clipped or
     faded, so collapsing never reflows the contents mid-transition -->
<aside
  class={[
    'border-surface-200-800 bg-surface-100-900 flex shrink-0 flex-col gap-4 border-b p-4 md:sticky md:top-0 md:h-dvh md:overflow-hidden md:border-r md:border-b-0 md:transition-[width] md:duration-200 md:ease-out',
    sidebar.isCollapsed ? 'md:w-18' : 'md:w-64',
  ]}
>
  <header class="flex items-center gap-3">
    <div class="group relative size-10 shrink-0">
      <Logo
        class={[
          'size-10 shadow-sm transition-opacity',
          sidebar.isCollapsed && 'md:group-hover:opacity-0 md:group-has-focus-visible:opacity-0',
        ]}
      />
      <!-- Collapsed, the logo doubles as the expand button -->
      {#if sidebar.isCollapsed}
        <button
          aria-expanded="false"
          aria-label={i18n.t.nav.expand}
          class="btn-icon text-surface-600-400 hover:preset-tint-primary absolute inset-0 hidden size-10 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 md:inline-flex"
          data-tippy-placement="right"
          onclick={toggle}
          title={i18n.t.nav.expand}
          type="button"
          bind:this={expandButton}
        >
          <PanelLeftOpen aria-hidden="true" size={ICON_SIZE} />
        </button>
      {/if}
    </div>
    <span
      class={[
        'h5 flex-1 whitespace-nowrap transition-opacity',
        sidebar.isCollapsed && 'md:opacity-0',
      ]}
    >
      {branding.appName}
    </span>
    <button
      aria-expanded="true"
      aria-label={i18n.t.nav.collapse}
      class={[
        'btn-icon text-surface-600-400 hover:preset-tint-primary hidden size-10 shrink-0 transition-[opacity,visibility] md:inline-flex',
        sidebar.isCollapsed && 'md:invisible md:opacity-0',
      ]}
      data-tippy-placement="right"
      onclick={toggle}
      title={i18n.t.nav.collapse}
      type="button"
      bind:this={collapseButton}
    >
      <PanelLeftClose aria-hidden="true" size={ICON_SIZE} />
    </button>
    <div class="md:hidden">
      <AccountMenu placement="bottom-end" variant="compact" />
    </div>
  </header>

  <nav
    aria-label={i18n.t.nav.label}
    class="flex gap-1 overflow-x-auto md:flex-1 md:flex-col md:overflow-visible"
  >
    {#each items as item (item.path)}
      <!-- Fixed padding centres the icon in the collapsed width, so it never moves -->
      <a
        aria-current={isActive(item.path) ? 'page' : undefined}
        aria-label={sidebar.isCollapsed ? i18n.t.nav[item.label] : undefined}
        class={[
          'btn h-10 justify-start gap-3 px-3',
          isActive(item.path) ? 'preset-filled-primary-500' : 'hover:preset-tint-primary',
        ]}
        data-tippy-placement="right"
        href={p(item.path)}
        title={sidebar.isCollapsed ? i18n.t.nav[item.label] : undefined}
      >
        <item.icon aria-hidden="true" class="shrink-0" size={ICON_SIZE} />
        <span class={['transition-opacity', sidebar.isCollapsed && 'md:opacity-0']}>
          {i18n.t.nav[item.label]}
        </span>
      </a>
    {/each}
  </nav>

  <footer class="border-surface-200-800 hidden border-t pt-2 md:flex">
    <AccountMenu
      isCondensed={sidebar.isCollapsed}
      placement={sidebar.isCollapsed ? 'right-end' : 'top-start'}
      variant="full"
    />
  </footer>
</aside>
