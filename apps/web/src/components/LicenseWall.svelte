<script lang="ts">
  import ShieldAlert from '@lucide/svelte/icons/shield-alert';

  import AccountMenu from '@/components/AccountMenu.svelte';
  import LicenseActivation from '@/components/LicenseActivation.svelte';
  import Logo from '@/components/Logo.svelte';
  import { formatDatetime } from '%/formatters.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { branding } from '%/useBranding.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { LicenseStatus } from '$/license.ts';

  type LicenseWallProps = {
    status: LicenseStatus;
  };

  const { status }: LicenseWallProps = $props();

  const ICON_SIZE = 18;

  const banner = $derived(
    status.state === 'expired'
      ? i18n.t.license.banner.expired
      : status.state === 'invalid'
        ? i18n.t.license.banner.invalid
        : i18n.t.license.banner.none
  );
</script>

<svelte:head>
  <title>{i18n.t.license.title} · {branding.appName}</title>
</svelte:head>

<div class="fixed top-4 right-4 z-10 flex items-center gap-1">
  <AccountMenu placement="bottom-end" variant="compact" />
</div>

<main class="grid min-h-dvh place-items-center p-4">
  <div class="w-full max-w-xl space-y-6">
    <header class="flex items-center justify-center gap-4 text-center">
      <Logo class="size-14 shadow-lg" />
      <h1 class="h3">{branding.appName}</h1>
    </header>

    <div class="card space-y-6 bg-surface-100-900 p-6 shadow-md">
      <div
        class="flex items-start gap-3 rounded-container bg-error-500/15 p-3 text-error-700-300"
        role="alert"
      >
        <ShieldAlert aria-hidden="true" class="mt-0.5 shrink-0" size={ICON_SIZE} />
        <div class="space-y-1">
          <p class="font-semibold">{banner}</p>
          {#if status.state === 'expired' && status.licensed_to && status.expires_at}
            <p class="text-sm">
              {i18n.t.license.holder}: {status.licensed_to} · {i18n.t.license.expires}:
              {formatDatetime(status.expires_at, config.current?.timezone ?? 'UTC')}
            </p>
          {/if}
        </div>
      </div>

      <LicenseActivation canActivate={auth.session?.user.role === 'admin'} />

      <p class="text-xs text-surface-600-400">
        {i18n.t.license.machineId}: <span class="font-mono">{status.machine_id}</span>
      </p>
    </div>
  </div>
</main>
