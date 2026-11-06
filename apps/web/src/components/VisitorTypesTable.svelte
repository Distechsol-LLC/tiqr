<script lang="ts">
  import CornerDownRight from '@lucide/svelte/icons/corner-down-right';
  import ListPlus from '@lucide/svelte/icons/list-plus';
  import Pencil from '@lucide/svelte/icons/pencil';
  import Percent from '@lucide/svelte/icons/percent';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import { onMount } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import VisitorSubtypeForm from '@/components/VisitorSubtypeForm.svelte';
  import VisitorTypeForm from '@/components/VisitorTypeForm.svelte';
  import { deleteVisitorType, fetchVisitorTypes } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { deleteVisitorSubtype } from '%/subtypeApi.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { mode } from '%/useMode.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import type { VisitorSubtype, VisitorType } from '$/catalog.ts';

  // Only names sort: a type has no discount of its own, so discounts give no order for types
  type SortKey = 'name';

  type VisitorTypesTableProps = {
    // Read by the page, which owns the refresh button
    isLoading?: boolean;
  };

  const ICON_SIZE = 18;
  const COLUMNS = 3;
  // A ticket mode type adds a subtype as well as editing and deleting itself
  const ACTIONS = 2;
  const TYPE_ACTIONS = 3;

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
  // The subtype dialog's type, and the subtype it changes; null adds one
  let subtypeParent = $state<VisitorType | null>(null);
  let editingSubtype = $state<VisitorSubtype | null>(null);
  let isSubtypeFormOpen = $state(false);
  let deletingSubtype = $state<{ parent: VisitorType; subtype: VisitorSubtype } | null>(null);
  let isSubtypeDeletePending = $state(false);

  // Under each type, the biggest discount comes first, and equal ones go by name
  const bySubtypeDiscount = (left: VisitorSubtype, right: VisitorSubtype): number =>
    right.discount_percent - left.discount_percent ||
    left.name.localeCompare(right.name, undefined, { numeric: true });

  const sortValues: SortValues<VisitorType, SortKey> = {
    name: (visitorType) => visitorType.name,
  };

  const sorting = createSortParams(sortValues, { direction: 'asc', key: 'name' });

  // Each type's subtypes sit under it, by discount, whichever way the types are sorted
  const rows = $derived(
    sortRows(visitorTypes, sorting.sort, sortValues).map((visitorType) => ({
      subtypes: mode.isBadge ? [] : visitorType.subtypes.toSorted(bySubtypeDiscount),
      visitorType,
    }))
  );

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

  const openSubtypeForm = (parent: VisitorType, subtype: VisitorSubtype | null): void => {
    subtypeParent = parent;
    editingSubtype = subtype;
    isSubtypeFormOpen = true;
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

  const confirmSubtypeDelete = async (): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;
    const target = deletingSubtype;

    if (!(csrfToken && target)) return;

    isSubtypeDeletePending = true;

    const result = await deleteVisitorSubtype(csrfToken, target.parent.id, target.subtype.id);

    isSubtypeDeletePending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.visitorTypes.subtypeNotDeleted, result.error);
      return;
    }

    toaster.success({
      description: target.subtype.name,
      title: i18n.t.visitorTypes.subtypeDeleted,
    });
    deletingSubtype = null;
    await reload();
  };

  onMount(() => {
    void reload();
  });

  export { create, reload };
</script>

<!-- Badges carry no price, so their visitor types have no discount column, nor subtypes. A ticket
     mode type lists its subtypes under it, which hold the discounts tickets get -->
<DataTable
  caption={i18n.t.visitorTypes.caption}
  columns={COLUMNS - (mode.isBadge ? 1 : 0)}
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
    {#if !mode.isBadge}
      <th class="w-40 text-right">{i18n.t.visitorTypes.columns.discount}</th>
    {/if}
    <ActionsHeader count={mode.isBadge ? ACTIONS : TYPE_ACTIONS} />
  {/snippet}

  {#each rows as { subtypes, visitorType } (visitorType.id)}
    <tr>
      <td class="font-semibold">{visitorType.name}</td>
      {#if !mode.isBadge}
        <td></td>
      {/if}
      <td>
        <div class="flex justify-start gap-1">
          {#if !mode.isBadge}
            <button
              aria-label={i18n.t.visitorTypes.addSubtypeFor(visitorType.name)}
              class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
              onclick={(): void => openSubtypeForm(visitorType, null)}
              title={i18n.t.visitorTypes.addSubtype}
              type="button"
            >
              <ListPlus aria-hidden="true" size={ICON_SIZE} />
            </button>
          {/if}
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
    {#if !mode.isBadge && subtypes.length === 0}
      <!-- A ticket needs a subtype, so a type without one can't be picked yet -->
      <tr>
        <td class="text-warning-700-300 text-sm" colspan={COLUMNS}>
          <span class="flex items-center gap-2 ps-6">
            <CornerDownRight aria-hidden="true" class="shrink-0 opacity-60" size={ICON_SIZE} />
            {i18n.t.visitorTypes.noSubtypes}
            <!-- An unseen, zero-width button, so the row stands as tall as a subtype's -->
            <span
              aria-hidden="true"
              class="btn-icon btn-icon-lg invisible w-0 min-w-0 overflow-hidden px-0"
            ></span>
          </span>
        </td>
      </tr>
    {/if}
    {#each subtypes as subtype (subtype.id)}
      <tr>
        <td>
          <span class="flex items-center gap-2 ps-6">
            <CornerDownRight aria-hidden="true" class="shrink-0 opacity-60" size={ICON_SIZE} />
            <span class="truncate">{subtype.name}</span>
          </span>
        </td>
        <td class="text-right tabular-nums">
          {i18n.t.visitorTypes.discount(subtype.discount_percent)}
        </td>
        <td>
          <div class="flex justify-start gap-1">
            <button
              aria-label={i18n.t.visitorTypes.editFor(subtype.name)}
              class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
              onclick={(): void => openSubtypeForm(visitorType, subtype)}
              title={i18n.t.visitorTypes.edit}
              type="button"
            >
              <Pencil aria-hidden="true" size={ICON_SIZE} />
            </button>
            <button
              aria-label={i18n.t.visitorTypes.deleteFor(subtype.name)}
              class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-error"
              onclick={(): void => {
                deletingSubtype = { parent: visitorType, subtype };
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

<!-- Names sort the list, so a new or renamed type may belong on another page -->
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
  <p>
    {#if deleting}
      {deleting.subtypes.length > 0 && !mode.isBadge
        ? i18n.t.visitorTypes.deleteConfirmWithSubtypes(deleting.name)
        : i18n.t.visitorTypes.deleteConfirm(deleting.name)}
    {/if}
  </p>
</FormDialog>
<VisitorSubtypeForm
  editing={editingSubtype}
  isOpen={isSubtypeFormOpen}
  onClose={(): void => {
    isSubtypeFormOpen = false;
  }}
  onSaved={(): void => {
    void reload();
  }}
  parent={subtypeParent}
/>
<FormDialog
  isDestructive
  isOpen={deletingSubtype !== null}
  isPending={isSubtypeDeletePending}
  onClose={(): void => {
    deletingSubtype = null;
  }}
  onSubmit={confirmSubtypeDelete}
  submitLabel={i18n.t.visitorTypes.delete}
  title={i18n.t.visitorTypes.deleteSubtypeTitle}
>
  <p>{deletingSubtype ? i18n.t.visitorTypes.deleteConfirm(deletingSubtype.subtype.name) : ''}</p>
</FormDialog>
