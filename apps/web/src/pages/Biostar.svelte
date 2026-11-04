<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Plug from '@lucide/svelte/icons/plug';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Unplug from '@lucide/svelte/icons/unplug';
  import { onMount } from 'svelte';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import {
    disconnectBiostar,
    fetchBiostar,
    fetchBiostarDevices,
    fetchBiostarLogs,
    saveBiostar,
  } from '%/api.ts';
  import { formatDatetime } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { Biostar, BiostarDevice, BiostarLog } from '$/biostar.ts';

  const ICON_SIZE = 18;

  let current = $state<Biostar | null>(null);
  let baseUrl = $state('');
  let username = $state('');
  let password = $state('');
  let deviceIds = $state('');
  let verifyTls = $state(false);
  let devices = $state<BiostarDevice[]>([]);
  let logs = $state<BiostarLog[]>([]);
  let isSaving = $state(false);
  let isLoadingLists = $state(false);
  let refusal = $state('');

  const text = $derived(i18n.t.biostar);
  const timezone = $derived(config.current?.timezone ?? 'UTC');
  const chosen = $derived(
    deviceIds
      .split(',')
      .map((id) => id.trim())
      .filter(Boolean)
  );

  const fill = (data: Biostar): void => {
    current = data;
    baseUrl = data.base_url;
    username = data.username;
    deviceIds = data.device_ids.join(',');
    verifyTls = data.verify_tls;
    password = '';
  };

  const loadLists = async (): Promise<void> => {
    if (!current?.configured) {
      devices = [];
      logs = [];
      return;
    }

    isLoadingLists = true;

    const [deviceResult, logResult] = await Promise.all([
      fetchBiostarDevices(),
      fetchBiostarLogs(),
    ]);

    isLoadingLists = false;

    if (deviceResult.ok) devices = deviceResult.data;
    else {
      devices = [];
      await notifyFailure(text.devicesFailed, deviceResult.error);
    }

    if (logResult.ok) logs = logResult.data;
    else {
      logs = [];
      await notifyFailure(text.logsFailed, logResult.error);
    }
  };

  const load = async (): Promise<void> => {
    const result = await fetchBiostar();

    if (!result.ok) {
      await notifyFailure(text.loadFailed, result.error);
      return;
    }

    fill(result.data);
    await loadLists();
  };

  const toggle = (id: string): void => {
    deviceIds = (chosen.includes(id) ? chosen.filter((item) => item !== id) : [...chosen, id]).join(
      ','
    );
  };

  const onToggle = (event: Event): void => {
    const { id } = (event.currentTarget as HTMLInputElement).dataset;

    if (id) toggle(id);
  };

  const save = async (event: SubmitEvent): Promise<void> => {
    event.preventDefault();

    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || isSaving) return;

    refusal = '';

    const hasPassword = Boolean(password) || current?.has_password;

    if (!(baseUrl.trim() && username.trim() && hasPassword) || chosen.length === 0) {
      refusal = text.required;
      return;
    }

    isSaving = true;

    const result = await saveBiostar(csrfToken, {
      base_url: baseUrl.trim(),
      device_ids: chosen,
      password,
      username: username.trim(),
      verify_tls: verifyTls,
    });

    isSaving = false;

    if (!result.ok) {
      if (result.error.kind === 'server' && result.error.detail) refusal = result.error.detail;
      else await notifyFailure(text.save, result.error);

      return;
    }

    toaster.success({ title: text.saved });
    fill(result.data);
    await loadLists();
  };

  const disconnect = async (): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || isSaving) return;

    isSaving = true;

    const result = await disconnectBiostar(csrfToken);

    isSaving = false;

    if (!result.ok) {
      await notifyFailure(text.disconnect, result.error);
      return;
    }

    toaster.success({ title: text.disconnected });
    await load();
  };

  onMount(() => {
    void config.load();
    void load();
  });
</script>

<PageHeader description={text.description} title={text.title} />

<div
  class="min-h-0 flex-1 overflow-y-auto bg-[light-dark(white,var(--color-surface-950))] p-4 md:p-8"
>
  <div class="mx-auto max-w-3xl space-y-10">
    <section class="space-y-4">
      <h2 class="h6">{text.connection}</h2>
      {#if current && !current.configured}
        <p class="text-surface-600-400 text-sm">{text.notConnected}</p>
      {/if}

      <form class="space-y-4" onsubmit={save}>
        <FloatingInput
          autocomplete="off"
          id="biostar-url"
          label={text.baseUrl}
          bind:value={baseUrl}
        />
        <FloatingInput
          autocomplete="off"
          id="biostar-username"
          label={text.username}
          bind:value={username}
        />
        <FloatingInput
          autocomplete="new-password"
          id="biostar-password"
          label={text.password}
          type="password"
          bind:value={password}
        />
        {#if current?.has_password}
          <p class="text-surface-600-400 -mt-2 text-xs">{text.passwordKept}</p>
        {/if}
        <FloatingInput
          autocomplete="off"
          id="biostar-devices"
          label={text.deviceIds}
          bind:value={deviceIds}
        />
        <p class="text-surface-600-400 -mt-2 text-xs">{text.deviceIdsHint}</p>

        <label class="flex items-center gap-2 text-sm">
          <input class="checkbox" type="checkbox" bind:checked={verifyTls} />
          {text.verifyTls}
        </label>

        {#if refusal}
          <p class="text-error-600-400 text-sm" role="alert">{refusal}</p>
        {/if}

        <div class="flex flex-wrap gap-2">
          <button
            class="btn preset-filled-primary-500 h-12 flex-1"
            disabled={isSaving}
            type="submit"
          >
            {#if isSaving}
              <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
            {:else}
              <Plug aria-hidden="true" size={ICON_SIZE} />
            {/if}
            {current?.configured ? text.save : text.connect}
          </button>
          {#if current?.configured}
            <button
              class="btn preset-tonal h-12"
              disabled={isSaving}
              onclick={disconnect}
              type="button"
            >
              <Unplug aria-hidden="true" size={ICON_SIZE} />
              {text.disconnect}
            </button>
          {/if}
        </div>
      </form>
    </section>

    {#if current?.configured}
      <section class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <h2 class="h6">{text.devices}</h2>
          <button
            aria-label={text.refresh}
            class="btn-icon preset-tonal"
            disabled={isLoadingLists}
            onclick={loadLists}
            title={text.refresh}
            type="button"
          >
            <RefreshCw
              aria-hidden="true"
              class={isLoadingLists ? 'animate-spin' : undefined}
              size={ICON_SIZE}
            />
          </button>
        </div>
        {#if devices.length === 0}
          <p class="text-surface-600-400 text-sm">{text.devicesEmpty}</p>
        {:else}
          <div class="table-wrap">
            <table class="table text-sm">
              <thead>
                <tr>
                  <th></th>
                  <th>ID</th>
                  <th>{text.deviceName}</th>
                  <th>{text.deviceAddress}</th>
                  <th>{text.deviceStatus}</th>
                </tr>
              </thead>
              <tbody>
                {#each devices as device (device.id)}
                  <tr>
                    <td>
                      <input
                        aria-label={device.name || device.id}
                        checked={chosen.includes(device.id)}
                        class="checkbox"
                        data-id={device.id}
                        onchange={onToggle}
                        type="checkbox"
                      />
                    </td>
                    <td class="font-mono">{device.id}</td>
                    <td>{device.name}</td>
                    <td class="font-mono">{device.address}</td>
                    <td>{device.status}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>
    {/if}

    {#if current?.configured}
      <section class="space-y-3">
        <h2 class="h6">{text.logs}</h2>
        {#if logs.length === 0}
          <p class="text-surface-600-400 text-sm">{text.logsEmpty}</p>
        {:else}
          <div class="table-wrap">
            <table class="table text-sm">
              <thead>
                <tr>
                  <th>{text.logTime}</th>
                  <th>{text.logReader}</th>
                  <th>{text.logDirection}</th>
                  <th>{text.logResult}</th>
                </tr>
              </thead>
              <tbody>
                {#each logs as log (log.event_id)}
                  <tr>
                    <td>{formatDatetime(log.event_time, timezone)}</td>
                    <td>{log.point_name ?? log.point_id ?? ''}</td>
                    <td>{log.direction ?? ''}</td>
                    <td>{log.granted ? text.granted : text.denied}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>
    {/if}
  </div>
</div>
