<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import { type Snippet, onMount } from 'svelte';

  import LicenseWall from '@/components/LicenseWall.svelte';
  import Sidebar from '@/components/Sidebar.svelte';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { branding } from '%/useBranding.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { license } from '%/useLicense.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';

  type DashboardProps = {
    children: Snippet;
  };

  const { children }: DashboardProps = $props();

  const ICON_SIZE = 18;

  const check = async (): Promise<void> => {
    const result = await license.refresh();

    // A session that ended is sent to sign-in; any other failure shows the retry screen
    if (!result.ok && result.error.kind === 'unauthenticated')
      await notifyFailure(i18n.t.license.checkFailed, result.error);
  };

  onMount(() => {
    void config.load();
    // Read again on entering, so a mode another admin switched to since the page loaded shows
    void branding.load();
    void check();
  });
</script>

<!-- Fail closed: the app shows only after a check that says the license is valid -->
{#if license.failed}
  <main class="grid min-h-dvh place-items-center p-4">
    <div class="space-y-4 text-center">
      <h1 class="h4">{i18n.t.license.checkFailed}</h1>
      <p class="text-surface-600-400">{i18n.t.license.checkFailedHint}</p>
      <button class="btn preset-filled-primary-500" onclick={check} type="button">
        <RefreshCw aria-hidden="true" size={ICON_SIZE} />
        {i18n.t.license.retry}
      </button>
    </div>
  </main>
{:else if !license.status}
  <main class="grid min-h-dvh place-items-center">
    <LoaderCircle
      aria-label={i18n.t.common.loading}
      class="animate-spin"
      role="status"
      size={ICON_SIZE * 2}
    />
  </main>
{:else if !license.status.is_valid}
  <LicenseWall status={license.status} />
{:else}
  <div class="flex min-h-dvh flex-col md:flex-row">
    <Sidebar />
    <!-- On wide screens the page is exactly the viewport: the header bar stays put and the table
         scrolls beneath it -->
    <main class="flex min-w-0 flex-1 flex-col md:h-dvh">
      {@render children()}
    </main>
  </div>
{/if}
