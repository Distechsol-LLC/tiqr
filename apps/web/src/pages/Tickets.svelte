<script lang="ts">
  import FileDown from '@lucide/svelte/icons/file-down';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Plus from '@lucide/svelte/icons/plus';
  import Printer from '@lucide/svelte/icons/printer';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Search from '@lucide/svelte/icons/search';
  import SearchX from '@lucide/svelte/icons/search-x';
  import Send from '@lucide/svelte/icons/send';
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import UserRoundPen from '@lucide/svelte/icons/user-round-pen';
  import { onMount, untrack } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import AssignForm from '@/components/AssignForm.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import StateBadge from '@/components/StateBadge.svelte';
  import TicketForm from '@/components/TicketForm.svelte';
  import { fetchAllUsers, fetchTicket, fetchTickets, printTicket, renderTicketPdf } from '%/api.ts';
  import { formatDatetime } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type Sort, type SortValues, sortRows, toggleSort } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import type { User } from '$/auth.ts';
  import { type Ticket, type TicketState, ticketStateSchema } from '$/tickets.ts';

  type Filter = TicketState | 'all';
  type RowAction = 'browser' | 'pdf' | 'print';
  type SortKey =
    | 'assignee'
    | 'prints'
    | 'serial'
    | 'state'
    | 'usage'
    | 'uses'
    | 'valid'
    | 'visitor';

  const ICON_SIZE = 18;
  const BASE_COLUMNS = 8;
  const FILTERS: Filter[] = ['all', ...ticketStateSchema.options];
  // Long enough for the browser to start the download before the URL goes
  const REVOKE_DELAY = 60_000;
  const STATE_ORDER = new Map(ticketStateSchema.options.map((state, index) => [state, index]));

  const role = $derived(auth.session?.user.role ?? 'operator');
  // Operators see only their own tickets and can't list accounts; only managers assign
  const isStaff = $derived(role !== 'operator');
  const canAssign = $derived(role === 'manager');
  const canServerPrint = $derived(config.current?.server_printing ?? false);
  // The assignee column is staff-only
  const columns = $derived(BASE_COLUMNS + (isStaff ? 1 : 0));
  // Download and PDF always, then printing on the server and assigning where they're offered
  const actionCount = $derived(2 + Number(canServerPrint) + Number(canAssign));

  const pagination = createPagination();

  let tickets = $state<Ticket[]>([]);
  let total = $state(0);
  // Counts the requests, so a slow one can't land over a newer one
  let requestId = 0;
  let accounts = $state<User[]>([]);
  let filter = $state<Filter>('all');
  let query = $state('');
  let sort = $state<Sort<SortKey> | null>(null);
  let isLoading = $state(true);
  let isCreating = $state(false);
  let assigning = $state<Ticket | null>(null);
  let pending = $state<{ action: RowAction; id: string } | null>(null);

  const usernames = $derived(new Map(accounts.map((account) => [account.id, account.username])));

  const sortValues: SortValues<Ticket, SortKey> = {
    assignee: (ticket) => usernames.get(ticket.assigned_operator) ?? '',
    prints: (ticket) => ticket.print_count,
    serial: (ticket) => ticket.readable_serial,
    state: (ticket) => STATE_ORDER.get(ticket.state) ?? 0,
    usage: (ticket) => i18n.t.usage[ticket.usage_type],
    uses: (ticket) => ticket.use_count,
    valid: (ticket) => Date.parse(ticket.valid_from),
    visitor: (ticket) => ticket.visitor_name,
  };

  // The API sends the newest tickets first, what people look for first, until a column is picked.
  // Searching and sorting only reach the page showing.
  const rows = $derived.by(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches = needle
      ? tickets.filter((ticket) =>
          [ticket.readable_serial, ticket.visitor_name, ticket.visitor_type].some((field) =>
            field.toLocaleLowerCase().includes(needle)
          )
        )
      : tickets;

    return sortRows(matches, sort, sortValues);
  });

  const load = async (state: Filter): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isLoading = true;

    const result = await fetchTickets(
      { page: pagination.page, size: pagination.size },
      state === 'all' ? undefined : state
    );

    // A newer filter or page may have been picked while this one loaded
    if (id !== requestId) return;

    if (!result.ok) {
      isLoading = false;
      await notifyFailure(i18n.t.tickets.notLoaded, result.error);
      return;
    }

    const last = pageCount(result.data.total, pagination.size);

    // A shared link can point past the end: show the last page
    if (pagination.page > last) {
      pagination.goTo(last);
      await load(state);
      return;
    }

    isLoading = false;
    tickets = result.data.items;
    total = result.data.total;
  };

  const loadAccounts = async (): Promise<void> => {
    const result = await fetchAllUsers();

    if (result.ok) accounts = result.data;
    else await notifyFailure(i18n.t.tickets.accountsNotLoaded, result.error);
  };

  const sortBy = (key: SortKey): void => {
    sort = toggleSort(sort, key);
  };

  const directionOf = (key: SortKey): Sort<SortKey>['direction'] | null =>
    sort?.key === key ? sort.direction : null;

  const refresh = (): void => {
    void load(filter);
  };

  const goToPage = (page: number): void => {
    pagination.goTo(page);
    refresh();
  };

  const resize = (size: number): void => {
    pagination.resize(size);
    refresh();
  };

  // New tickets are the newest, so they open the first page
  const showNewest = (): void => {
    goToPage(1);
  };

  const replace = (ticket: Ticket): void => {
    tickets = tickets.map((current) => (current.id === ticket.id ? ticket : current));
  };

  // Renders the PDF and hands its URL to `open`; every render counts as a print
  const renderBadge = async (
    ticket: Ticket,
    action: RowAction,
    open: (url: string) => void
  ): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || pending) return;

    pending = { action, id: ticket.id };

    const result = await renderTicketPdf(csrfToken, ticket.id);

    pending = null;

    if (!result.ok) {
      await notifyFailure(i18n.t.tickets.badgeNotRendered, result.error);
      return;
    }

    const url = URL.createObjectURL(result.data);

    open(url);
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY);

    const updated = await fetchTicket(ticket.id);

    if (updated.ok) replace(updated.data);
  };

  const download = (ticket: Ticket): Promise<void> =>
    renderBadge(ticket, 'pdf', (url) => {
      const link = document.createElement('a');

      link.href = url;
      link.download = `${ticket.readable_serial}.pdf`;
      link.click();
    });

  // A hidden frame loads the PDF, so the print dialog covers the page rather than a new tab
  const printPdf = (ticket: Ticket): Promise<void> =>
    renderBadge(ticket, 'browser', (url) => {
      const frame = document.createElement('iframe');

      frame.hidden = true;
      frame.src = url;
      frame.onload = (): void => {
        frame.contentWindow?.addEventListener('afterprint', () => frame.remove(), { once: true });
        frame.contentWindow?.print();
      };
      document.body.append(frame);
    });

  const print = async (ticket: Ticket): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || pending) return;

    pending = { action: 'print', id: ticket.id };

    const result = await printTicket(csrfToken, ticket.id);

    pending = null;

    if (!result.ok) {
      await notifyFailure(i18n.t.tickets.badgeNotPrinted, result.error);
      return;
    }

    replace(result.data);
    toaster.success({
      description: result.data.readable_serial,
      title: i18n.t.tickets.sentToPrinter,
    });
  };

  const closeCreate = (): void => {
    isCreating = false;
  };

  const closeAssign = (): void => {
    assigning = null;
  };

  const isPending = (ticket: Ticket, action: RowAction): boolean =>
    pending?.id === ticket.id && pending.action === action;

  $effect(() => {
    const state = filter;

    untrack(() => {
      void load(state);
    });
  });

  onMount(() => {
    void config.load();

    if (isStaff) void loadAccounts();
  });
</script>

<PageHeader
  description={isStaff ? i18n.t.tickets.descriptionStaff : i18n.t.tickets.descriptionOwn}
  title={i18n.t.tickets.title}
>
  {#snippet actions()}
    <button
      aria-label={i18n.t.common.refresh}
      class="btn-icon size-11 preset-tonal"
      disabled={isLoading}
      onclick={refresh}
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
      class="btn h-11 min-w-36 preset-filled-primary-500"
      onclick={(): void => {
        isCreating = true;
      }}
      type="button"
    >
      <Plus aria-hidden="true" size={ICON_SIZE} />
      {i18n.t.tickets.new}
    </button>
  {/snippet}
  {#snippet toolbar()}
    <div class="flex flex-wrap items-center justify-between gap-3">
      <fieldset class="flex flex-wrap gap-2">
        <legend class="sr-only">{i18n.t.tickets.filter}</legend>
        {#each FILTERS as option (option)}
          <button
            aria-pressed={filter === option}
            class={['chip', filter === option ? 'preset-filled-primary-500' : 'preset-tonal']}
            onclick={(): void => {
              if (option === filter) return;

              // The effect below loads the new filter; the old page number means nothing to it
              pagination.goTo(1);
              filter = option;
            }}
            type="button"
          >
            {option === 'all' ? i18n.t.tickets.all : i18n.t.states[option]}
          </button>
        {/each}
      </fieldset>

      <label class="relative w-full sm:w-72">
        <span class="sr-only">{i18n.t.tickets.search}</span>
        <Search
          aria-hidden="true"
          class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-[color:light-dark(var(--color-surface-300),var(--color-surface-400))]"
          size={ICON_SIZE}
        />
        <input
          class="input bg-surface-100-900 pl-10 ring-surface-200-800 [--field-placeholder:light-dark(var(--color-surface-300),var(--color-surface-400))]"
          placeholder={i18n.t.tickets.searchPlaceholder}
          type="search"
          bind:value={query}
        />
      </label>
    </div>
  {/snippet}
</PageHeader>

<DataTable
  caption={i18n.t.tickets.title}
  {columns}
  emptyIcon={query ? SearchX : TicketIcon}
  emptyMessage={query ? i18n.t.tickets.emptySearch : i18n.t.tickets.empty}
  isEmpty={rows.length === 0}
  {isLoading}
  minWidth="72rem"
>
  {#snippet head()}
    <SortHeader
      class="w-48"
      direction={directionOf('serial')}
      label={i18n.t.tickets.columns.serial}
      onSort={(): void => sortBy('serial')}
    />
    <SortHeader
      direction={directionOf('visitor')}
      label={i18n.t.tickets.columns.visitor}
      onSort={(): void => sortBy('visitor')}
    />
    <SortHeader
      class="w-34"
      direction={directionOf('usage')}
      label={i18n.t.tickets.columns.usage}
      onSort={(): void => sortBy('usage')}
    />
    <SortHeader
      class="w-36"
      direction={directionOf('valid')}
      label={i18n.t.tickets.columns.valid}
      onSort={(): void => sortBy('valid')}
    />
    <SortHeader
      class="w-32"
      direction={directionOf('state')}
      label={i18n.t.tickets.columns.state}
      onSort={(): void => sortBy('state')}
    />
    {#if isStaff}
      <SortHeader
        class="w-30"
        direction={directionOf('assignee')}
        label={i18n.t.tickets.columns.assignee}
        onSort={(): void => sortBy('assignee')}
      />
    {/if}
    <SortHeader
      class="w-24"
      direction={directionOf('prints')}
      isEnd
      label={i18n.t.tickets.columns.prints}
      onSort={(): void => sortBy('prints')}
    />
    <SortHeader
      class="w-24"
      direction={directionOf('uses')}
      isEnd
      label={i18n.t.tickets.columns.uses}
      onSort={(): void => sortBy('uses')}
    />
    <ActionsHeader count={actionCount} />
  {/snippet}

  {#each rows as ticket (ticket.id)}
    <tr>
      <td class="font-mono">{ticket.readable_serial}</td>
      <td>
        <p class="font-semibold">{ticket.visitor_name}</p>
        <p class="text-surface-600-400 text-xs">{ticket.visitor_type}</p>
      </td>
      <td>{i18n.t.usage[ticket.usage_type]}</td>
      <td>
        <p>{formatDatetime(ticket.valid_from, ticket.timezone)}</p>
        <p class="text-surface-600-400 text-xs">
          {formatDatetime(ticket.valid_until, ticket.timezone)}
        </p>
      </td>
      <td>
        <StateBadge state={ticket.state} />
        {#if ticket.passed_at}
          <p class="mt-1 text-surface-600-400 text-xs" title={i18n.t.tickets.firstPassage}>
            {formatDatetime(ticket.passed_at, ticket.timezone)}
          </p>
        {/if}
      </td>
      {#if isStaff}
        <td>{usernames.get(ticket.assigned_operator) ?? '—'}</td>
      {/if}
      <td class="text-right tabular-nums">{ticket.print_count}</td>
      <td class="text-right tabular-nums">{ticket.use_count}</td>
      <td>
        <div class="flex justify-start gap-1">
          <!-- The API prints only issued tickets, as many times as needed -->
          <button
            aria-label={i18n.t.tickets.downloadFor(ticket.readable_serial)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
            disabled={ticket.state !== 'issued' || pending !== null}
            onclick={(): Promise<void> => download(ticket)}
            title={i18n.t.tickets.download}
            type="button"
          >
            {#if isPending(ticket, 'pdf')}
              <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
            {:else}
              <FileDown aria-hidden="true" size={ICON_SIZE} />
            {/if}
          </button>
          <button
            aria-label={i18n.t.tickets.printPdfFor(ticket.readable_serial)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
            disabled={ticket.state !== 'issued' || pending !== null}
            onclick={(): Promise<void> => printPdf(ticket)}
            title={i18n.t.tickets.printPdf}
            type="button"
          >
            {#if isPending(ticket, 'browser')}
              <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
            {:else}
              <Printer aria-hidden="true" size={ICON_SIZE} />
            {/if}
          </button>
          {#if canServerPrint}
            <button
              aria-label={i18n.t.tickets.printFor(ticket.readable_serial)}
              class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
              disabled={ticket.state !== 'issued' || pending !== null}
              onclick={(): Promise<void> => print(ticket)}
              title={i18n.t.tickets.print}
              type="button"
            >
              {#if isPending(ticket, 'print')}
                <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
              {:else}
                <Send aria-hidden="true" size={ICON_SIZE} />
              {/if}
            </button>
          {/if}
          {#if canAssign}
            <button
              aria-label={i18n.t.tickets.assignFor(ticket.readable_serial)}
              class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
              onclick={(): void => {
                assigning = ticket;
              }}
              title={i18n.t.tickets.assign}
              type="button"
            >
              <UserRoundPen aria-hidden="true" size={ICON_SIZE} />
            </button>
          {/if}
        </div>
      </td>
    </tr>
  {/each}
</DataTable>

<Pagination
  {isLoading}
  onPage={goToPage}
  onSize={resize}
  page={pagination.page}
  size={pagination.size}
  {total}
/>

<TicketForm isOpen={isCreating} onClose={closeCreate} onCreated={showNewest} />

{#if canAssign}
  <AssignForm {accounts} onAssigned={replace} onClose={closeAssign} ticket={assigning} />
{/if}
