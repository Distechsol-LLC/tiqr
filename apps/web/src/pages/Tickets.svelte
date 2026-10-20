<script lang="ts">
  import FileDown from '@lucide/svelte/icons/file-down';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Plus from '@lucide/svelte/icons/plus';
  import Printer from '@lucide/svelte/icons/printer';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Search from '@lucide/svelte/icons/search';
  import UserRoundPen from '@lucide/svelte/icons/user-round-pen';
  import { onMount, untrack } from 'svelte';

  import AssignForm from '@/components/AssignForm.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import StateBadge from '@/components/StateBadge.svelte';
  import TicketForm from '@/components/TicketForm.svelte';
  import { fetchTicket, fetchTickets, fetchUsers, printTicket, renderTicketPdf } from '%/api.ts';
  import { STATE_LABELS, USAGE_LABELS, formatDatetime } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import type { User } from '$/auth.ts';
  import { type Ticket, type TicketState, ticketStateSchema } from '$/tickets.ts';

  type Filter = TicketState | 'all';
  type RowAction = 'pdf' | 'print';

  const ICON_SIZE = 18;
  const BASE_COLUMNS = 8;
  const FILTERS: Filter[] = ['all', ...ticketStateSchema.options];
  // Long enough for the browser to start the download before the URL goes
  const REVOKE_DELAY = 60_000;

  const role = $derived(auth.session?.user.role ?? 'operator');
  // Operators see only their own tickets and can't list accounts; only managers assign
  const isStaff = $derived(role !== 'operator');
  const canAssign = $derived(role === 'manager');
  const canServerPrint = $derived(config.current?.server_printing ?? false);
  // The assignee column is staff-only
  const columns = $derived(BASE_COLUMNS + (isStaff ? 1 : 0));

  let tickets = $state<Ticket[]>([]);
  let accounts = $state<User[]>([]);
  let filter = $state<Filter>('all');
  let query = $state('');
  let isLoading = $state(true);
  let isCreating = $state(false);
  let assigning = $state<Ticket | null>(null);
  let pending = $state<{ action: RowAction; id: string } | null>(null);

  const usernames = $derived(new Map(accounts.map((account) => [account.id, account.username])));

  // The API sorts by serial; the newest tickets are what people look for first
  const rows = $derived.by(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches = needle
      ? tickets.filter((ticket) =>
          [ticket.readable_serial, ticket.visitor_name, ticket.visitor_type].some((field) =>
            field.toLocaleLowerCase().includes(needle)
          )
        )
      : tickets;

    return matches.toReversed();
  });

  const load = async (state: Filter): Promise<void> => {
    isLoading = true;

    const result = await fetchTickets(state === 'all' ? undefined : state);

    // A newer filter may have been picked while this one loaded
    if (state !== filter) return;

    isLoading = false;

    if (result.ok) tickets = result.data;
    else await notifyFailure('Tickets not loaded', result.error);
  };

  const loadAccounts = async (): Promise<void> => {
    const result = await fetchUsers();

    if (result.ok) accounts = result.data;
    else await notifyFailure('Accounts not loaded', result.error);
  };

  const refresh = (): void => {
    void load(filter);
  };

  const replace = (ticket: Ticket): void => {
    tickets = tickets.map((current) => (current.id === ticket.id ? ticket : current));
  };

  const download = async (ticket: Ticket): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || pending) return;

    pending = { action: 'pdf', id: ticket.id };

    const result = await renderTicketPdf(csrfToken, ticket.id);

    pending = null;

    if (!result.ok) {
      await notifyFailure('Badge not rendered', result.error);
      return;
    }

    const url = URL.createObjectURL(result.data);
    const link = document.createElement('a');

    link.href = url;
    link.download = `${ticket.readable_serial}.pdf`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY);

    // Every render counts as a print
    const updated = await fetchTicket(ticket.id);

    if (updated.ok) replace(updated.data);
  };

  const print = async (ticket: Ticket): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || pending) return;

    pending = { action: 'print', id: ticket.id };

    const result = await printTicket(csrfToken, ticket.id);

    pending = null;

    if (!result.ok) {
      await notifyFailure('Badge not printed', result.error);
      return;
    }

    replace(result.data);
    toaster.success({ description: result.data.readable_serial, title: 'Sent to the printer' });
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
  description={isStaff ? 'Every ticket, in every state.' : 'Tickets assigned to you.'}
  title="Tickets"
>
  {#snippet actions()}
    <button
      aria-label="Refresh"
      class="btn-icon preset-tonal"
      disabled={isLoading}
      onclick={refresh}
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
      class="btn preset-filled-primary-500"
      onclick={(): void => {
        isCreating = true;
      }}
      type="button"
    >
      <Plus aria-hidden="true" size={ICON_SIZE} />
      New ticket
    </button>
  {/snippet}
</PageHeader>

<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
  <fieldset class="flex flex-wrap gap-2">
    <legend class="sr-only">Filter by state</legend>
    {#each FILTERS as option (option)}
      <button
        aria-pressed={filter === option}
        class={['chip', filter === option ? 'preset-filled-primary-500' : 'preset-tonal']}
        onclick={(): void => {
          filter = option;
        }}
        type="button"
      >
        {option === 'all' ? 'All' : STATE_LABELS[option]}
      </button>
    {/each}
  </fieldset>

  <label class="relative w-full sm:w-72">
    <span class="sr-only">Search tickets</span>
    <Search
      aria-hidden="true"
      class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-surface-600-400"
      size={ICON_SIZE}
    />
    <input
      class="input pl-10"
      placeholder="Serial, name or type"
      type="search"
      bind:value={query}
    />
  </label>
</div>

<DataTable
  caption="Tickets"
  {columns}
  emptyMessage={query ? 'No tickets match the search.' : 'No tickets yet.'}
  isEmpty={rows.length === 0}
  {isLoading}
>
  {#snippet head()}
    <th>Serial</th>
    <th>Visitor</th>
    <th>Usage</th>
    <th>Valid</th>
    <th>State</th>
    {#if isStaff}
      <th>Assignee</th>
    {/if}
    <th class="text-right">Prints</th>
    <th class="text-right">Uses</th>
    <th><span class="sr-only">Actions</span></th>
  {/snippet}

  {#each rows as ticket (ticket.id)}
    <tr>
      <td class="font-mono whitespace-nowrap">{ticket.readable_serial}</td>
      <td>
        <p class="font-semibold">{ticket.visitor_name}</p>
        <p class="text-surface-600-400 text-xs">{ticket.visitor_type}</p>
      </td>
      <td class="whitespace-nowrap">{USAGE_LABELS[ticket.usage_type]}</td>
      <td class="whitespace-nowrap">
        <p>{formatDatetime(ticket.valid_from, ticket.timezone)}</p>
        <p class="text-surface-600-400 text-xs">
          until {formatDatetime(ticket.valid_until, ticket.timezone)}
        </p>
      </td>
      <td>
        <StateBadge state={ticket.state} />
        {#if ticket.passed_at}
          <p class="mt-1 whitespace-nowrap text-surface-600-400 text-xs" title="First passage">
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
        <div class="flex justify-end gap-1">
          <!-- The API prints only issued tickets, as many times as needed -->
          <button
            aria-label={`Download badge for ${ticket.readable_serial}`}
            class="btn-icon btn-icon-sm hover:preset-tonal"
            disabled={ticket.state !== 'issued' || pending !== null}
            onclick={(): Promise<void> => download(ticket)}
            title="Download badge"
            type="button"
          >
            {#if isPending(ticket, 'pdf')}
              <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
            {:else}
              <FileDown aria-hidden="true" size={ICON_SIZE} />
            {/if}
          </button>
          {#if canServerPrint}
            <button
              aria-label={`Print badge for ${ticket.readable_serial}`}
              class="btn-icon btn-icon-sm hover:preset-tonal"
              disabled={ticket.state !== 'issued' || pending !== null}
              onclick={(): Promise<void> => print(ticket)}
              title="Print on the server"
              type="button"
            >
              {#if isPending(ticket, 'print')}
                <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
              {:else}
                <Printer aria-hidden="true" size={ICON_SIZE} />
              {/if}
            </button>
          {/if}
          {#if canAssign}
            <button
              aria-label={`Assign ${ticket.readable_serial}`}
              class="btn-icon btn-icon-sm hover:preset-tonal"
              onclick={(): void => {
                assigning = ticket;
              }}
              title="Assign"
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

<TicketForm isOpen={isCreating} onClose={closeCreate} onCreated={refresh} />

{#if canAssign}
  <AssignForm {accounts} onAssigned={replace} onClose={closeAssign} ticket={assigning} />
{/if}
