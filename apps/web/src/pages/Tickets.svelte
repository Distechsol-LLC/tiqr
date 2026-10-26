<script lang="ts">
  import DoorOpen from '@lucide/svelte/icons/door-open';
  import FileDown from '@lucide/svelte/icons/file-down';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Printer from '@lucide/svelte/icons/printer';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Search from '@lucide/svelte/icons/search';
  import SearchX from '@lucide/svelte/icons/search-x';
  import Send from '@lucide/svelte/icons/send';
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import TicketsIcon from '@lucide/svelte/icons/tickets';
  import UserRoundPen from '@lucide/svelte/icons/user-round-pen';
  import X from '@lucide/svelte/icons/x';
  import { onMount, untrack } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import AssignForm from '@/components/AssignForm.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import FilterTabs from '@/components/FilterTabs.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import StateBadge from '@/components/StateBadge.svelte';
  import TicketForm from '@/components/TicketForm.svelte';
  import { fetchAllUsers, fetchTicket, fetchTickets, printTicket, renderTicketPdf } from '%/api.ts';
  import { formatDatetime } from '%/formatters.ts';
  import { formatMinor } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { tooltipIfTruncated } from '%/tooltipIfTruncated.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import type { User } from '$/auth.ts';
  import { type Ticket, type TicketState, ticketStateSchema } from '$/tickets.ts';

  type Filter = TicketState | 'all';
  type RowAction = 'browser' | 'pdf' | 'print';
  type SortKey = 'assignee' | 'price' | 'state' | 'valid' | 'visitor';

  const ICON_SIZE = 18;
  const SMALL_ICON_SIZE = 14;
  const USAGE_ICON_SIZE = 16;
  const BASE_COLUMNS = 7;
  const FILTERS: Filter[] = ['all', ...ticketStateSchema.options];
  // Long enough for the browser to start the download before the URL goes
  const REVOKE_DELAY = 60_000;
  const STATE_ORDER = new Map(ticketStateSchema.options.map((state, index) => [state, index]));
  // Same bound as the API's search
  const SEARCH_MAX = 200;
  // Pause after typing before asking the server, so each keystroke doesn't send a request
  const SEARCH_DELAY = 300;

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
  // What the input says, and the search the list is showing
  let query = $state('');
  let search = $state('');
  let isLoading = $state(true);
  let isCreating = $state(false);
  let assigning = $state<Ticket | null>(null);
  let pending = $state<{ action: RowAction; id: string } | null>(null);

  const usernames = $derived(new Map(accounts.map((account) => [account.id, account.username])));

  const sortValues: SortValues<Ticket, SortKey> = {
    assignee: (ticket) => usernames.get(ticket.assigned_operator) ?? '',
    price: (ticket) => ticket.price_minor ?? -1,
    state: (ticket) => STATE_ORDER.get(ticket.state) ?? 0,
    valid: (ticket) => Date.parse(ticket.valid_from),
    visitor: (ticket) => ticket.visitor_name,
  };

  const sorting = createSortParams(sortValues, { direction: 'asc', key: 'valid' });

  // The server filters and pages; sorting only reorders the page showing.
  const rows = $derived(sortRows(tickets, sorting.sort, sortValues));

  const load = async (state: Filter, term: string): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isLoading = true;

    const result = await fetchTickets(
      { page: pagination.page, size: pagination.size },
      state === 'all' ? undefined : state,
      term
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
      await load(state, term);
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

  const refresh = (): void => {
    void load(filter, search);
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

  // A new search starts from the first page, as a new filter does
  $effect(() => {
    const term = query.trim();
    const timer = setTimeout(() => {
      if (term === search) return;

      pagination.goTo(1);
      search = term;
    }, SEARCH_DELAY);

    return (): void => clearTimeout(timer);
  });

  $effect(() => {
    const state = filter;
    const term = search;

    untrack(() => {
      void load(state, term);
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
      <TicketIcon aria-hidden="true" size={ICON_SIZE} />
      {i18n.t.tickets.new}
    </button>
  {/snippet}
  {#snippet toolbar()}
    <!-- The tabs' negative bottom margin eats into the row gap, so the wrapped row needs more -->
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-4">
      <FilterTabs
        label={(option): string => (option === 'all' ? i18n.t.tickets.all : i18n.t.states[option])}
        legend={i18n.t.tickets.filter}
        onpick={(option): void => {
          if (option === filter) return;

          // The effect below loads the new filter; the old page number means nothing to it
          pagination.goTo(1);
          filter = option;
        }}
        options={FILTERS}
        selected={filter}
      />

      <label class="relative order-first sm:order-none sm:w-72">
        <span class="sr-only">{i18n.t.tickets.search}</span>
        <Search
          aria-hidden="true"
          class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-[color:light-dark(var(--color-surface-300),var(--color-surface-400))]"
          size={ICON_SIZE}
        />
        <input
          class="input bg-surface-50-950 px-10 ring-surface-200-800 [--field-placeholder:light-dark(var(--color-surface-300),var(--color-surface-400))] [&::-webkit-search-cancel-button]:appearance-none"
          maxlength={SEARCH_MAX}
          placeholder={i18n.t.tickets.searchPlaceholder}
          type="search"
          bind:value={query}
        />
        {#if query}
          <button
            aria-label={i18n.t.tickets.clearSearch}
            class="btn-icon absolute top-1/2 right-2 -translate-y-1/2 hover:preset-tint-primary"
            onclick={(): void => {
              query = '';
            }}
            title={i18n.t.tickets.clearSearch}
            type="button"
          >
            <X aria-hidden="true" size={ICON_SIZE} />
          </button>
        {/if}
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
  minWidth="88rem"
>
  {#snippet head()}
    <th class="w-48">{i18n.t.tickets.columns.serial}</th>
    <SortHeader
      class="w-48"
      direction={sorting.directionOf('visitor')}
      label={i18n.t.tickets.columns.visitor}
      onSort={(): void => sorting.sortBy('visitor')}
    />
    <SortHeader
      class="w-36"
      direction={sorting.directionOf('valid')}
      label={i18n.t.tickets.columns.valid}
      onSort={(): void => sorting.sortBy('valid')}
    />
    <SortHeader
      class="w-32"
      direction={sorting.directionOf('state')}
      label={i18n.t.tickets.columns.state}
      onSort={(): void => sorting.sortBy('state')}
    />
    <SortHeader
      class="w-28"
      direction={sorting.directionOf('price')}
      isEnd
      label={i18n.t.tickets.columns.price}
      onSort={(): void => sorting.sortBy('price')}
    />
    <th class="w-28">{i18n.t.tickets.columns.usage}</th>
    {#if isStaff}
      <SortHeader
        class="w-30"
        direction={sorting.directionOf('assignee')}
        label={i18n.t.tickets.columns.assignee}
        onSort={(): void => sorting.sortBy('assignee')}
      />
    {/if}
    <ActionsHeader count={actionCount} />
  {/snippet}

  {#each rows as ticket (ticket.id)}
    <tr>
      <td>
        <div class="flex items-center gap-2 font-mono" {@attach tooltipIfTruncated}>
          <!-- The usage as an icon, so the column stays narrow; the tooltip names it -->
          <span
            aria-label={i18n.t.usage[ticket.usage_type]}
            class="inline-flex shrink-0 text-surface-600-400"
            role="img"
            title={i18n.t.usage[ticket.usage_type]}
          >
            {#if ticket.usage_type === 'one_time'}
              <TicketIcon aria-hidden="true" size={USAGE_ICON_SIZE} />
            {:else}
              <TicketsIcon aria-hidden="true" size={USAGE_ICON_SIZE} />
            {/if}
          </span>
          {ticket.readable_serial}
        </div>
      </td>
      <td>
        <p class="font-semibold" {@attach tooltipIfTruncated}>{ticket.visitor_name}</p>
        <p class="text-surface-600-400 text-xs" {@attach tooltipIfTruncated}>
          {ticket.visitor_type}
        </p>
      </td>
      <td>
        <p {@attach tooltipIfTruncated}>{formatDatetime(ticket.valid_from, ticket.timezone)}</p>
        <p class="text-surface-600-400 text-xs" {@attach tooltipIfTruncated}>
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
      <td class="text-right">
        <p class="tabular-nums" {@attach tooltipIfTruncated}>
          {ticket.price_minor === null || ticket.currency === null
            ? '—'
            : formatMinor(ticket.price_minor, ticket.currency)}
        </p>
        {#if ticket.price_minor !== null}
          <!-- The type and discount it was priced with, as they were when it was made -->
          <p class="text-surface-600-400 text-xs" {@attach tooltipIfTruncated}>
            {[ticket.discount_percent > 0 && `−${ticket.discount_percent}%`, ticket.ticket_type]
              .filter(Boolean)
              .join(' · ')}
          </p>
        {/if}
      </td>
      <td>
        <!-- Prints and uses, each with an icon that the tooltip names -->
        <p class="flex items-center gap-3 text-surface-600-400 text-xs tabular-nums">
          <span class="inline-flex items-center gap-1" title={i18n.t.tickets.columns.prints}>
            <Printer aria-hidden="true" size={SMALL_ICON_SIZE} />
            {ticket.print_count}
          </span>
          <span class="inline-flex items-center gap-1" title={i18n.t.tickets.columns.uses}>
            <DoorOpen aria-hidden="true" size={SMALL_ICON_SIZE} />
            {ticket.use_count}
          </span>
        </p>
      </td>
      {#if isStaff}
        <td {@attach tooltipIfTruncated}>{usernames.get(ticket.assigned_operator) ?? '—'}</td>
      {/if}
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
