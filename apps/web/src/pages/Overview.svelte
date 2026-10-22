<script lang="ts">
  import ChartColumn from '@lucide/svelte/icons/chart-column';
  import Eraser from '@lucide/svelte/icons/eraser';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import { onMount } from 'svelte';

  import DataTable from '@/components/DataTable.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import { type ApiResult, fetchStats, runCleanup, runSync } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { type Sort, type SortValues, sortRows, toggleSort } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { Counts, Stats } from '$/operations.ts';

  type Operation = 'cleanup' | 'sync';
  type Metric = keyof Counts;
  type SortKey = 'count' | 'meaning' | 'metric';

  const ICON_SIZE = 18;
  const COLUMNS = 3;
  // The fixed columns and room for the meanings, then each visitor type's column on top
  const MIN_REM = 40;
  const VISITOR_TYPE_REM = 8;

  // The same figures as `tiqr stats`, in its order; each is labelled in the showing language
  const METRICS: Metric[] = ['total', 'issued', 'passed', 'expired', 'uses', 'prints'];

  // Toasts are worded by the locale's entry of the same name
  const OPERATIONS: Record<Operation, (csrfToken: string) => Promise<ApiResult<number>>> = {
    cleanup: runCleanup,
    sync: runSync,
  };

  let stats = $state<Stats | null>(null);
  let sort = $state<Sort<SortKey> | null>(null);
  let isLoading = $state(true);
  let running = $state<Operation | null>(null);

  const sortValues: SortValues<Metric, SortKey> = {
    count: (metric) => stats?.[metric] ?? 0,
    meaning: (metric) => i18n.t.overview.metrics[metric].description,
    metric: (metric) => i18n.t.overview.metrics[metric].label,
  };

  const rows = $derived(sortRows(METRICS, sort, sortValues));
  // One column per visitor type, in the order the server sends them
  const visitorTypes = $derived(stats ? Object.keys(stats.visitor_types) : []);

  const sortBy = (key: SortKey): void => {
    sort = toggleSort(sort, key);
  };

  const directionOf = (key: SortKey): Sort<SortKey>['direction'] | null =>
    sort?.key === key ? sort.direction : null;

  const load = async (): Promise<void> => {
    isLoading = true;

    const result = await fetchStats();

    isLoading = false;

    if (result.ok) stats = result.data;
    else await notifyFailure(i18n.t.overview.notLoaded, result.error);
  };

  // The server also runs both on a schedule; these start one now
  const run = async (operation: Operation): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || running) return;

    running = operation;

    const result = await OPERATIONS[operation](csrfToken);

    running = null;

    // Read after the wait, in case the language changed meanwhile
    const text = i18n.t.overview[operation];

    if (!result.ok) {
      await notifyFailure(text.failed, result.error);
      return;
    }

    toaster.success({ description: text.done(result.data), title: text.finished });
    await load();
  };

  onMount(() => {
    void load();
  });
</script>

<PageHeader description={i18n.t.overview.description} title={i18n.t.overview.title}>
  {#snippet actions()}
    <button
      aria-label={i18n.t.common.refresh}
      class="btn-icon size-11 preset-tonal"
      disabled={isLoading}
      onclick={load}
      title={i18n.t.common.refresh}
      type="button"
    >
      <RefreshCw
        aria-hidden="true"
        class={isLoading ? 'animate-spin' : undefined}
        size={ICON_SIZE}
      />
    </button>
    <button
      class="btn h-11 min-w-36 preset-tonal"
      disabled={running !== null}
      onclick={(): Promise<void> => run('cleanup')}
      title={i18n.t.overview.cleanup.hint}
      type="button"
    >
      {#if running === 'cleanup'}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else}
        <Eraser aria-hidden="true" size={ICON_SIZE} />
      {/if}
      {i18n.t.overview.cleanup.action}
    </button>
    <button
      class="btn h-11 min-w-36 preset-filled-primary-500"
      disabled={running !== null}
      onclick={(): Promise<void> => run('sync')}
      title={i18n.t.overview.sync.hint}
      type="button"
    >
      {#if running === 'sync'}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else}
        <RefreshCw aria-hidden="true" size={ICON_SIZE} />
      {/if}
      {i18n.t.overview.sync.action}
    </button>
  {/snippet}
</PageHeader>

<DataTable
  caption={i18n.t.overview.caption}
  columns={COLUMNS + visitorTypes.length}
  emptyIcon={ChartColumn}
  emptyMessage={i18n.t.overview.empty}
  isEmpty={stats === null}
  {isLoading}
  minWidth="{MIN_REM + VISITOR_TYPE_REM * visitorTypes.length}rem"
>
  {#snippet head()}
    <SortHeader
      class="w-44"
      direction={directionOf('metric')}
      label={i18n.t.overview.columns.metric}
      onSort={(): void => sortBy('metric')}
    />
    <SortHeader
      class="w-36"
      direction={directionOf('count')}
      isEnd
      label={i18n.t.overview.columns.count}
      onSort={(): void => sortBy('count')}
    />
    {#each visitorTypes as name (name)}
      <th class="w-32 text-right" title={name}>
        <span class="inline-block max-w-full truncate align-bottom">{name}</span>
      </th>
    {/each}
    <!-- Without a set width, it takes the spare width, so the figures stay beside their labels -->
    <SortHeader
      direction={directionOf('meaning')}
      label={i18n.t.overview.columns.meaning}
      onSort={(): void => sortBy('meaning')}
    />
  {/snippet}

  {#if stats}
    {#each rows as metric (metric)}
      <tr>
        <td class="font-semibold">{i18n.t.overview.metrics[metric].label}</td>
        <td class="text-right text-lg tabular-nums">{stats[metric]}</td>
        {#each visitorTypes as name (name)}
          <td class="text-right tabular-nums">{stats.visitor_types[name][metric]}</td>
        {/each}
        <td class="text-surface-600-400">{i18n.t.overview.metrics[metric].description}</td>
      </tr>
    {/each}
  {/if}
</DataTable>
