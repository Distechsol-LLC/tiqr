<script lang="ts">
  import Eraser from '@lucide/svelte/icons/eraser';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import { onMount } from 'svelte';

  import DataTable from '@/components/DataTable.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import { type ApiResult, fetchStats, runCleanup, runSync } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import type { Stats } from '$/operations.ts';

  type Operation = 'cleanup' | 'sync';

  const ICON_SIZE = 18;
  const COLUMNS = 3;

  // The same figures as `tiqr stats`, in its order
  const METRICS: { key: keyof Stats; label: string; description: string }[] = [
    { description: 'Every ticket ever issued', key: 'total', label: 'Total' },
    { description: 'Waiting for their first passage', key: 'issued', label: 'Issued' },
    { description: 'Passed at least once, still valid', key: 'passed', label: 'Passed' },
    { description: 'Past their validity window', key: 'expired', label: 'Expired' },
    { description: 'Granted passages applied to tickets', key: 'uses', label: 'Uses' },
    { description: 'Badges rendered or printed', key: 'prints', label: 'Prints' },
  ];

  const OPERATIONS: Record<
    Operation,
    {
      run: (csrfToken: string) => Promise<ApiResult<number>>;
      title: string;
      done: (count: number) => string;
    }
  > = {
    cleanup: {
      done: (count) =>
        `${count} finished ${count === 1 ? 'ticket' : 'tickets'} removed from BioStar.`,
      run: runCleanup,
      title: 'Cleanup',
    },
    sync: {
      done: (count) => `${count} new access ${count === 1 ? 'event' : 'events'} applied.`,
      run: runSync,
      title: 'Sync',
    },
  };

  let stats = $state<Stats | null>(null);
  let isLoading = $state(true);
  let running = $state<Operation | null>(null);

  const load = async (): Promise<void> => {
    isLoading = true;

    const result = await fetchStats();

    isLoading = false;

    if (result.ok) stats = result.data;
    else await notifyFailure('Statistics not loaded', result.error);
  };

  // The server also runs both on a schedule; these start one now
  const run = async (operation: Operation): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || running) return;

    const { done, run: start, title } = OPERATIONS[operation];

    running = operation;

    const result = await start(csrfToken);

    running = null;

    if (!result.ok) {
      await notifyFailure(`${title} failed`, result.error);
      return;
    }

    toaster.success({ description: done(result.data), title: `${title} finished` });
    await load();
  };

  onMount(() => {
    void load();
  });
</script>

<PageHeader description="Ticket figures, and BioStar maintenance on demand." title="Overview">
  {#snippet actions()}
    <button
      aria-label="Refresh"
      class="btn-icon preset-tonal"
      disabled={isLoading}
      onclick={load}
      title="Refresh"
      type="button"
    >
      <RefreshCw
        aria-hidden="true"
        class={isLoading ? 'animate-spin' : undefined}
        size={ICON_SIZE}
      />
    </button>
    <button
      class="btn preset-tonal"
      disabled={running !== null}
      onclick={(): Promise<void> => run('cleanup')}
      title="Remove expired and spent one-time tickets from BioStar"
      type="button"
    >
      {#if running === 'cleanup'}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else}
        <Eraser aria-hidden="true" size={ICON_SIZE} />
      {/if}
      Clean up
    </button>
    <button
      class="btn preset-filled-primary-500"
      disabled={running !== null}
      onclick={(): Promise<void> => run('sync')}
      title="Fetch and apply new access events from BioStar"
      type="button"
    >
      {#if running === 'sync'}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else}
        <RefreshCw aria-hidden="true" size={ICON_SIZE} />
      {/if}
      Sync now
    </button>
  {/snippet}
</PageHeader>

<DataTable
  caption="Ticket statistics"
  columns={COLUMNS}
  emptyMessage="No statistics."
  isEmpty={stats === null}
  {isLoading}
>
  {#snippet head()}
    <th>Metric</th>
    <th>Meaning</th>
    <th class="text-right">Count</th>
  {/snippet}

  {#if stats}
    {#each METRICS as metric (metric.key)}
      <tr>
        <td class="font-semibold">{metric.label}</td>
        <td class="text-surface-600-400">{metric.description}</td>
        <td class="text-right text-lg tabular-nums">{stats[metric.key]}</td>
      </tr>
    {/each}
  {/if}
</DataTable>
