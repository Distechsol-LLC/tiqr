<script lang="ts">
  import { onMount } from 'svelte';

  import LicenseActivation from '@/components/LicenseActivation.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import { formatDatetime } from '%/formatters.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { license } from '%/useLicense.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';

  const status = $derived(license.status);
  const timezone = $derived(config.current?.timezone ?? 'UTC');

  onMount(() => {
    void config.load();
    void license.refresh();
  });
</script>

<PageHeader description={i18n.t.license.description} title={i18n.t.license.title} />

<div class="min-h-0 flex-1 overflow-y-auto p-4 md:p-8">
  <div class="mx-auto max-w-xl space-y-8">
    {#if status}
      <dl class="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt class="text-surface-600-400">{i18n.t.license.status}</dt>
        <dd class="font-semibold">{i18n.t.license.states[status.state]}</dd>
        {#if status.type}
          <dt class="text-surface-600-400">{i18n.t.license.type}</dt>
          <dd>{i18n.t.license.types[status.type]}</dd>
        {/if}
        {#if status.licensed_to}
          <dt class="text-surface-600-400">{i18n.t.license.holder}</dt>
          <dd>{status.licensed_to}</dd>
        {/if}
        {#if status.expires_at}
          <dt class="text-surface-600-400">{i18n.t.license.expires}</dt>
          <dd>
            {formatDatetime(status.expires_at, timezone)}
            {#if status.days_remaining !== null}
              · {i18n.t.license.daysLeft(status.days_remaining)}
            {/if}
          </dd>
        {/if}
        <dt class="text-surface-600-400">{i18n.t.license.machineId}</dt>
        <dd class="font-mono break-all">{status.machine_id}</dd>
      </dl>
    {/if}

    <LicenseActivation canActivate />
  </div>
</div>
