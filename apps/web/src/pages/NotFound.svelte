<script lang="ts">
  import ArrowLeft from '@lucide/svelte/icons/arrow-left';

  import LanguageMenu from '@/components/LanguageMenu.svelte';
  import Logo from '@/components/Logo.svelte';
  import ThemeToggle from '@/components/ThemeToggle.svelte';
  import { p } from '@/router.ts';
  import { branding } from '%/useBranding.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';

  const ICON_SIZE = 18;
</script>

<svelte:head>
  <title>{i18n.t.notFound.title} · {branding.appName}</title>
</svelte:head>

<!-- Float in the corner here; the sidebar places them inline instead -->
<div class="fixed top-4 right-4 z-10 flex items-center gap-1">
  <LanguageMenu class="size-12" />
  <ThemeToggle class="size-12" />
</div>

<main class="grid min-h-dvh place-items-center p-4">
  <div class="flex flex-col items-center gap-6 text-center">
    <Logo class="size-16" />
    <div class="space-y-1">
      <h1 class="h3">{i18n.t.notFound.title}</h1>
      <p class="text-surface-600-400">{i18n.t.notFound.description}</p>
    </div>
    <a class="btn preset-tonal" href={p('/')}>
      <ArrowLeft aria-hidden="true" size={ICON_SIZE} />
      {i18n.t.notFound.back}
    </a>
  </div>
</main>
