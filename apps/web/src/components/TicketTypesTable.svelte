<script lang="ts">
  import Pencil from '@lucide/svelte/icons/pencil';
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import { onMount } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import TicketTypeForm from '@/components/TicketTypeForm.svelte';
  import { deleteTicketType, fetchTicketTypes } from '%/api.ts';
  import { formatMinor } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import type { TicketType } from '$/catalog.ts';

  type SortKey = 'name' | 'price';

  type TicketTypesTableProps = {
    // Read by the page, which owns the refresh button
    isLoading?: boolean;
  };

  const ICON_SIZE = 18;
  const COLUMNS = 3;
  const ACTIONS = 2;

  let { isLoading = $bindable(true) }: TicketTypesTableProps = $props();

  const pagination = createPagination();

  let ticketTypes = $state<TicketType[]>([]);
  let total = $state(0);
  // Counts the requests, so a slow one can't land over a newer one
  let requestId = 0;
  let isFormOpen = $state(false);
  let editing = $state<TicketType | null>(null);
  let deleting = $state<TicketType | null>(null);
  let isDeletePending = $state(false);

  const sortValues: SortValues<TicketType, SortKey> = {
    name: (ticketType) => ticketType.name,
    price: (ticketType) => ticketType.price_minor,
  };

  const sorting = createSortParams(sortValues, { direction: 'desc', key: 'price' });

  const rows = $derived(sortRows(ticketTypes, sorting.sort, sortValues));

  const reload = async (): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isLoading = true;

    const result = await fetchTicketTypes({ page: pagination.page, size: pagination.size });

    if (id !== requestId) return;

    if (!result.ok) {
      isLoading = false;
      await notifyFailure(i18n.t.ticketTypes.notLoaded, result.error);
      return;
    }

    const last = pageCount(result.data.total, pagination.size);

    // A shared link, or deletions, can leave the page past the end: show the last one
    if (pagination.page > last) {
      pagination.goTo(last);
      await reload();
      return;
    }

    isLoading = false;
    ticketTypes = result.data.items;
    total = result.data.total;
  };

  const create = (): void => {
    editing = null;
    isFormOpen = true;
  };

  const goToPage = (page: number): void => {
    pagination.goTo(page);
    void reload();
  };

  const resize = (size: number): void => {
    pagination.resize(size);
    void reload();
  };

  const confirmDelete = async (): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;
    const ticketType = deleting;

    if (!(csrfToken && ticketType)) return;

    isDeletePending = true;

    const result = await deleteTicketType(csrfToken, ticketType.id);

    isDeletePending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.ticketTypes.notDeleted, result.error);
      return;
    }

    toaster.success({ description: ticketType.name, title: i18n.t.ticketTypes.deleted });
    deleting = null;
    await reload();
  };

  onMount(() => {
    void reload();
  });

  export { create, reload };
</script>

<DataTable
  caption={i18n.t.ticketTypes.caption}
  columns={COLUMNS}
  emptyIcon={TicketIcon}
  emptyMessage={i18n.t.ticketTypes.empty}
  isEmpty={rows.length === 0}
  {isLoading}
  minWidth="36rem"
>
  {#snippet head()}
    <SortHeader
      direction={sorting.directionOf('name')}
      label={i18n.t.ticketTypes.columns.name}
      onSort={(): void => sorting.sortBy('name')}
    />
    <SortHeader
      class="w-40"
      direction={sorting.directionOf('price')}
      isEnd
      label={i18n.t.ticketTypes.columns.price}
      onSort={(): void => sorting.sortBy('price')}
    />
    <ActionsHeader count={ACTIONS} />
  {/snippet}

  {#each rows as ticketType (ticketType.id)}
    <tr>
      <td class="font-semibold">{ticketType.name}</td>
      <td class="text-right tabular-nums">
        {formatMinor(ticketType.price_minor, ticketType.currency)}
      </td>
      <td>
        <div class="flex justify-start gap-1">
          <button
            aria-label={i18n.t.ticketTypes.editFor(ticketType.name)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
            onclick={(): void => {
              editing = ticketType;
              isFormOpen = true;
            }}
            title={i18n.t.ticketTypes.edit}
            type="button"
          >
            <Pencil aria-hidden="true" size={ICON_SIZE} />
          </button>
          <button
            aria-label={i18n.t.ticketTypes.deleteFor(ticketType.name)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-error"
            onclick={(): void => {
              deleting = ticketType;
            }}
            title={i18n.t.ticketTypes.delete}
            type="button"
          >
            <Trash2 aria-hidden="true" size={ICON_SIZE} />
          </button>
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

<!-- Prices sort the list, so a new or repriced type may belong on another page -->
<TicketTypeForm
  {editing}
  isOpen={isFormOpen}
  onClose={(): void => {
    isFormOpen = false;
  }}
  onSaved={(): void => {
    void reload();
  }}
/>
<FormDialog
  isDestructive
  isOpen={deleting !== null}
  isPending={isDeletePending}
  onClose={(): void => {
    deleting = null;
  }}
  onSubmit={confirmDelete}
  submitLabel={i18n.t.ticketTypes.delete}
  title={i18n.t.ticketTypes.deleteTitle}
>
  <p>{deleting ? i18n.t.ticketTypes.deleteConfirm(deleting.name) : ''}</p>
</FormDialog>
