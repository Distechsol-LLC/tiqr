<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import LogOut from '@lucide/svelte/icons/log-out';

  import Logo from '@/components/Logo.svelte';
  import ThemeToggle from '@/components/ThemeToggle.svelte';
  import { NAV } from '@/config/nav.ts';
  import { isActive, navigate, p } from '@/router.ts';
  import { ROLE_LABELS } from '%/formatters.ts';
  import { auth } from '%/useAuth.svelte.ts';

  const ICON_SIZE = 18;

  let isPending = $state(false);

  const user = $derived(auth.session?.user);
  const items = $derived(user ? NAV[user.role] : []);

  const handleSignOut = async (): Promise<void> => {
    isPending = true;
    await auth.signOut();
    await navigate('/login', { replace: true });
  };
</script>

{#snippet signOut()}
  <button
    aria-label="Sign out"
    class="btn-icon size-10 hover:preset-tonal"
    disabled={isPending}
    onclick={handleSignOut}
    title="Sign out"
    type="button"
  >
    {#if isPending}
      <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
    {:else}
      <LogOut aria-hidden="true" size={ICON_SIZE} />
    {/if}
  </button>
{/snippet}

<aside
  class="flex shrink-0 flex-col gap-4 border-surface-200-800 border-b bg-surface-100-900 p-4 md:sticky md:top-0 md:h-dvh md:w-64 md:border-r md:border-b-0"
>
  <header class="flex items-center gap-3">
    <Logo class="size-10 shadow-sm" />
    <span class="h5 flex-1">TiQR</span>
    <div class="flex items-center gap-1 md:hidden">
      <ThemeToggle class="size-10" />
      {@render signOut()}
    </div>
  </header>

  <nav
    aria-label="Main"
    class="flex gap-1 overflow-x-auto md:flex-1 md:flex-col md:overflow-visible"
  >
    {#each items as item (item.path)}
      <a
        aria-current={isActive(item.path) ? 'page' : undefined}
        class={[
          'btn justify-start gap-3',
          isActive(item.path) ? 'preset-filled-primary-500' : 'hover:preset-tonal',
        ]}
        href={p(item.path)}
      >
        <item.icon aria-hidden="true" size={ICON_SIZE} />
        {item.label}
      </a>
    {/each}
  </nav>

  {#if user}
    <footer class="hidden items-center gap-2 border-surface-200-800 border-t pt-4 md:flex">
      <div class="min-w-0 flex-1">
        <p class="truncate font-semibold" title={user.username}>{user.username}</p>
        <p class="text-sm text-surface-600-400">{ROLE_LABELS[user.role]}</p>
      </div>
      <ThemeToggle class="size-10" />
      {@render signOut()}
    </footer>
  {/if}
</aside>
