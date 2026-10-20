<script lang="ts">
  import ArrowLeft from '@lucide/svelte/icons/arrow-left';

  import Logo from '@/components/Logo.svelte';
  import { p } from '@/router.ts';

  const ICON_SIZE = 18;
</script>

<svelte:head>
  <title>Page not found · TiQR</title>
</svelte:head>

<main class="grid min-h-dvh place-items-center p-4">
  <div class="flex flex-col items-center gap-6 text-center">
    <Logo class="size-16" />
    <div class="space-y-1">
      <h1 class="h3">Page not found</h1>
      <p class="text-surface-600-400">The page you're looking for doesn't exist.</p>
    </div>
    <a class="btn preset-tonal" href={p('/')}>
      <ArrowLeft aria-hidden="true" size={ICON_SIZE} />
      Back to TiQR
    </a>
  </div>
</main>
