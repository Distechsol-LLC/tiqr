<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import LogOut from '@lucide/svelte/icons/log-out';

  import Logo from '@/components/Logo.svelte';
  import { navigate } from '@/router.ts';
  import { auth } from '%/useAuth.svelte.ts';

  const ICON_SIZE = 18;

  let isPending = $state(false);

  const handleSignOut = async (): Promise<void> => {
    isPending = true;
    await auth.signOut();
    await navigate('/login', { replace: true });
  };
</script>

<svelte:head>
  <title>TiQR</title>
</svelte:head>

<main class="grid min-h-dvh place-items-center p-4">
  <div class="flex flex-col items-center gap-6 text-center">
    <Logo class="size-16" />
    <div class="space-y-1">
      <h1 class="h3">TiQR</h1>
      {#if auth.session}
        <p class="text-surface-600-400">
          Signed in as <strong>{auth.session.user.username}</strong>
          ({auth.session.user.role})
        </p>
      {/if}
    </div>
    <button class="btn preset-tonal" disabled={isPending} onclick={handleSignOut} type="button">
      {#if isPending}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else}
        <LogOut aria-hidden="true" size={ICON_SIZE} />
      {/if}
      Sign out
    </button>
  </div>
</main>
