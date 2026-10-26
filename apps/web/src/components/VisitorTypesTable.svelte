<script lang="ts">
  import Pencil from '@lucide/svelte/icons/pencil';
  import Percent from '@lucide/svelte/icons/percent';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import { onMount } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import VisitorTypeForm from '@/components/VisitorTypeForm.svelte';
  import { deleteVisitorType, fetchVisitorTypes } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import type { VisitorType } from '$/catalog.ts';

  type SortKey = 'discount' | 'name';

  type VisitorTypesTableProps = {
    // Read by the page, which owns the refresh button
    isLoading?: boolean;
  };

  const ICON_SIZE = 18;
  const COLUMNS = 3;
  const ACTIONS = 2;

  let { isLoading = $bindable(true) }: VisitorTypesTableProps = $props();

  const pagination = createPagination();

  let visitorTypes = $state<VisitorType[]>([]);
  let total = $state(0);
  // Counts the requests, so a slow one can't land over a newer one
  let requestId = 0;
  let isFormOpen = $state(false);
  let editing = $state<VisitorType | null>(null);
  let deleting = $state<VisitorType | null>(null);
  let isDeletePending = $state(false);

  const sortValues: SortValues<VisitorType, SortKey> = {
    discount: (visitorType) => visitorType.discount_percent,
    name: (visitorType) => visitorType.name,
  };

  const sorting = createSortParams(sortValues, { direction: 'desc', key: 'discount' });

  const rows = $derived(sortRows(visitorTypes, sorting.sort, sortValues));

  const reload = async (): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isLoading = true;

    const result = await fetchVisitorTypes({ page: pagination.page, size: pagination.size });

    if (id !== requestId) return;

    if (!result.ok) {
      isLoading = false;
      await notifyFailure(i18n.t.visitorTypes.notLoaded, result.error);
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
    visitorTypes = result.data.items;
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
    const visitorType = deleting;

    if (!(csrfToken && visitorType)) return;

    isDeletePending = true;

    const result = await deleteVisitorType(csrfToken, visitorType.id);

    isDeletePending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.visitorTypes.notDeleted, result.error);
      return;
    }

    toaster.success({ description: visitorType.name, title: i18n.t.visitorTypes.deleted });
    deleting = null;
    await reload();
  };

  onMount(() => {
    void reload();
  });

  export { create, reload };
</script>

<DataTable
  caption={i18n.t.visitorTypes.caption}
  columns={COLUMNS}
  emptyIcon={Percent}
  emptyMessage={i18n.t.visitorTypes.empty}
  isEmpty={rows.length === 0}
  {isLoading}
  minWidth="36rem"
>
  {#snippet head()}
    <SortHeader
      direction={sorting.directionOf('name')}
      label={i18n.t.visitorTypes.columns.name}
      onSort={(): void => sorting.sortBy('name')}
    />
    <SortHeader
      class="w-40"
      direction={sorting.directionOf('discount')}
      isEnd
      label={i18n.t.visitorTypes.columns.discount}
      onSort={(): void => sorting.sortBy('discount')}
    />
    <ActionsHeader count={ACTIONS} />
  {/snippet}

  {#each rows as visitorType (visitorType.id)}
    <tr>
      <td class="font-semibold">{visitorType.name}</td>
      <td class="text-right tabular-nums">
        {i18n.t.visitorTypes.discount(visitorType.discount_percent)}
      </td>
      <td>
        <div class="flex justify-start gap-1">
          <button
            aria-label={i18n.t.visitorTypes.editFor(visitorType.name)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
            onclick={(): void => {
              editing = visitorType;
              isFormOpen = true;
            }}
            title={i18n.t.visitorTypes.edit}
            type="button"
          >
            <Pencil aria-hidden="true" size={ICON_SIZE} />
          </button>
          <button
            aria-label={i18n.t.visitorTypes.deleteFor(visitorType.name)}
            class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-error"
            onclick={(): void => {
              deleting = visitorType;
            }}
            title={i18n.t.visitorTypes.delete}
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

<!-- Discounts sort the list, so a new or changed type may belong on another page -->
<VisitorTypeForm
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
  submitLabel={i18n.t.visitorTypes.delete}
  title={i18n.t.visitorTypes.deleteTitle}
>
  <p>{deleting ? i18n.t.visitorTypes.deleteConfirm(deleting.name) : ''}</p>
</FormDialog>
