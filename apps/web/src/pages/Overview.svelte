<script lang="ts">
  import ChartColumn from '@lucide/svelte/icons/chart-column';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import Download from '@lucide/svelte/icons/download';
  import Eraser from '@lucide/svelte/icons/eraser';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import { searchParams } from 'sv-router';
  import { onMount } from 'svelte';

  import DataTable from '@/components/DataTable.svelte';
  import FilterTabs from '@/components/FilterTabs.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import PeriodPicker from '@/components/PeriodPicker.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import { type ApiResult, fetchStats, runCleanup, runSync } from '%/api.ts';
  import { downloadCsv, toCsv } from '%/csv.ts';
  import { toLocalInput } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { type DateRange, type Span, moveAnchor, shiftAnchor, spanOf } from '%/statsRange.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import { type Counts, METRICS, type Stats } from '$/operations.ts';

  type Operation = 'cleanup' | 'sync';
  type Range = Span | 'all' | 'range';
  type Metric = keyof Counts;
  type SortKey = 'count';

  const ICON_SIZE = 18;
  const COLUMNS = 3;
  // The fixed columns and room for the meanings, then each visitor type's column on top
  const MIN_REM = 40;
  const VISITOR_TYPE_REM = 8;

  const RANGES: Range[] = ['all', 'day', 'month', 'year', 'range'];

  const SEARCH_KEYS = ['range', 'date', 'since', 'until'];
  const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
  // The length of a period's first day in YYYY-MM-DD, which names the file
  const SCOPE_LENGTH: Record<Span, number> = { day: 10, month: 7, year: 4 };

  const readDay = (key: string): string => {
    const value = searchParams.get(key);

    return typeof value === 'string' && ISO_DAY.test(value) ? value : '';
  };

  const readSpan = (): string[] => {
    const since = readDay('since');

    return since ? [since, readDay('until') || since] : [];
  };

  const readRange = (): Range =>
    RANGES.find((option) => option === searchParams.get('range')) ?? 'all';

  // Toasts are worded by the locale's entry of the same name
  const OPERATIONS: Record<Operation, (csrfToken: string) => Promise<ApiResult<number>>> = {
    cleanup: runCleanup,
    sync: runSync,
  };

  let stats = $state<Stats | null>(null);
  // The period comes from the URL, so a reload or a shared link asks for the same figures
  let range = $state<Range>(readRange());
  // Any day in the day, month or year showing; kept across them, so a day picked opens its month
  let anchor = $state(readDay('date'));
  let span = $state<string[]>(readSpan());
  let isLoading = $state(true);
  let running = $state<Operation | null>(null);
  let isExporting = $state(false);

  const sortValues: SortValues<Metric, SortKey> = {
    count: (metric) => stats?.[metric] ?? 0,
  };

  const sorting = createSortParams(sortValues, { direction: 'desc', key: 'count' });

  // Days are the server's, as are the tickets' creation times it counts by
  const timeZone = $derived(
    config.current?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone
  );
  const today = $derived(toLocalInput(new Date(), timeZone).slice(0, 10));

  const dates = $derived.by((): DateRange | undefined => {
    if (range === 'all') return undefined;
    if (range !== 'range') return spanOf(range, anchor || today);

    const [since = today, until = since] = span;

    return { since, until };
  });

  // Nothing after today has tickets yet
  const isLatest = $derived(
    range !== 'all' && range !== 'range' && spanOf(range, anchor || today).until >= today
  );

  const rows = $derived(sortRows(METRICS, sorting.sort, sortValues));
  // One column per visitor type, in the order the server sends them
  const visitorTypes = $derived(stats ? Object.keys(stats.visitor_types) : []);

  const keyOf = (requested: DateRange | undefined): string =>
    requested ? `${requested.since}/${requested.until}` : 'all';

  // Mirrors the period in the URL; all time leaves it bare
  const writeSearch = (): void => {
    const options = { replace: true };

    for (const key of SEARCH_KEYS) searchParams.delete(key, undefined, options);

    if (!dates) return;

    searchParams.set('range', range, options);

    if (range === 'range') {
      searchParams.set('since', dates.since, options);
      searchParams.set('until', dates.until, options);
    } else {
      searchParams.set('date', anchor || today, options);
    }
  };

  const load = async (): Promise<void> => {
    const requested = dates;

    writeSearch();
    isLoading = true;

    const result = await fetchStats(requested);

    // Newer dates may have been picked while these loaded
    if (keyOf(requested) !== keyOf(dates)) return;

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

  // The period showing, as the table has it; the file names the day, month or year
  const exportCsv = async (): Promise<void> => {
    isExporting = true;

    const result = await fetchStats(dates);

    isExporting = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.overview.export.failed, result.error);
      return;
    }

    const figures = result.data;
    const types = Object.keys(figures.visitor_types);
    const csvRows = [
      [
        i18n.t.overview.columns.metric,
        i18n.t.overview.columns.count,
        ...types,
        i18n.t.overview.columns.meaning,
      ],
      ...METRICS.map((metric) => [
        i18n.t.overview.metrics[metric].label,
        String(figures[metric]),
        ...types.map((name) => String(figures.visitor_types[name][metric])),
        i18n.t.overview.metrics[metric].description,
      ]),
    ];
    const period =
      !dates || range === 'all'
        ? 'all-time'
        : range === 'range'
          ? `${dates.since}_${dates.until}`
          : dates.since.slice(0, SCOPE_LENGTH[range]);

    downloadCsv(`tiqr-stats-${period}.csv`, toCsv(csvRows));
  };

  const pick = (option: Range): void => {
    if (option === range) return;

    anchor ||= today;

    // A range starts as the month so far, around the day last showing
    if (option === 'range' && span.length === 0) {
      const month = spanOf('month', anchor);

      // ISO days sort in time order
      const [until = today] = [month.until, today].toSorted();

      span = [month.since, until];
    }

    range = option;
    void load();
  };

  const pickDates = (next: string[]): void => {
    const [picked] = next;

    if (range === 'range') span = next;
    else if (range !== 'all' && picked) anchor = moveAnchor(range, anchor || today, picked);

    void load();
  };

  const step = (by: number): void => {
    if (range === 'all' || range === 'range') return;

    anchor = shiftAnchor(range, anchor || today, by);
    void load();
  };

  onMount(() => {
    void config.load();
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
      aria-label={i18n.t.overview.export.hint}
      class="btn-icon size-11 preset-tonal"
      disabled={isExporting}
      onclick={exportCsv}
      title={i18n.t.overview.export.hint}
      type="button"
    >
      <Download aria-hidden="true" size={ICON_SIZE} />
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
  {#snippet toolbar()}
    <!-- As tall as the period controls, so the bar keeps its height when they come and go -->
    <div class="flex sm:flex-row sm:mt-0 min-h-9 flex-wrap items-center justify-between gap-x-3">
      <!-- A line of its own at the tabs' height, so they stay put whether or not the picker wraps -->
      <div class="flex h-9 items-end">
        <FilterTabs
          label={(option): string => i18n.t.overview.ranges[option]}
          legend={i18n.t.overview.range}
          onpick={pick}
          options={RANGES}
          selected={range}
        />
      </div>

      {#if range !== 'all'}
        <div class="order-first flex items-center gap-2 sm:order-none">
          {#if range !== 'range'}
            <button
              aria-label={i18n.t.overview.earlier}
              class="btn-icon size-9 preset-filled-surface-50-950 border border-surface-200-800 enabled:hover:border-primary-500"
              onclick={(): void => step(-1)}
              title={i18n.t.overview.earlier}
              type="button"
            >
              <ChevronLeft aria-hidden="true" size={ICON_SIZE} />
            </button>
          {/if}
          <PeriodPicker
            label={i18n.t.overview.pick}
            max={today}
            mode={range}
            {timeZone}
            bind:value={(): string[] => (range === 'range' ? span : [anchor || today]), pickDates}
          />
          {#if range !== 'range'}
            <button
              aria-label={i18n.t.overview.later}
              class="btn-icon size-9 preset-filled-surface-50-950 border border-surface-200-800 enabled:hover:border-primary-500"
              disabled={isLatest}
              onclick={(): void => step(1)}
              title={i18n.t.overview.later}
              type="button"
            >
              <ChevronRight aria-hidden="true" size={ICON_SIZE} />
            </button>
          {/if}
        </div>
      {/if}
    </div>
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
    <th class="w-44">{i18n.t.overview.columns.metric}</th>
    <SortHeader
      class="w-36"
      direction={sorting.directionOf('count')}
      isEnd
      label={i18n.t.overview.columns.count}
      onSort={(): void => sorting.sortBy('count')}
    />
    {#each visitorTypes as name (name)}
      <th class="w-32 text-right" title={name}>
        <span class="inline-block max-w-full truncate align-bottom">{name}</span>
      </th>
    {/each}
    <!-- Without a set width, it takes the spare width, so the figures stay beside their labels -->
    <th>{i18n.t.overview.columns.meaning}</th>
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
