<script lang="ts">
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';

  import { itemRange, pageCount } from '%/pagination.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { PAGE_SIZES } from '$/pagination.ts';

  type PaginationProps = {
    page: number;
    size: number;
    total: number;
    isLoading: boolean;
    onPage: (page: number) => void;
    onSize: (size: number) => void;
  };

  const ICON_SIZE = 18;
  const SELECT_ID = 'page-size';

  const { page, size, total, isLoading, onPage, onSize }: PaginationProps = $props();

  const pages = $derived(pageCount(total, size));
  const [from, to] = $derived(itemRange(page, size, total));
</script>

<!-- The footer bar, colored like the header above the table -->
<footer
  class="border-surface-200-800 bg-surface-100-900 flex h-18 shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t px-4 py-3 text-sm md:px-8"
>
  <div class="flex items-center gap-2">
    <label class="text-surface-700-300" for={SELECT_ID}>{i18n.t.common.rowsPerPage}</label>
    <select
      class="select h-9 w-20"
      id={SELECT_ID}
      onchange={(event): void => onSize(Number(event.currentTarget.value))}
      value={size}
    >
      {#each PAGE_SIZES as option (option)}
        <option value={option}>{option}</option>
      {/each}
    </select>
  </div>

  <div class="flex items-center gap-3">
    <span class="text-surface-700-300 tabular-nums">{i18n.t.common.range(from, to, total)}</span>
    <span aria-live="polite" class="tabular-nums">{i18n.t.common.pageOf(page, pages)}</span>
    <div class="flex items-center gap-2">
      <button
        aria-label={i18n.t.common.previousPage}
        class="btn-icon preset-tonal size-9"
        disabled={isLoading || page <= 1}
        onclick={(): void => onPage(page - 1)}
        title={i18n.t.common.previousPage}
        type="button"
      >
        <ChevronLeft aria-hidden="true" size={ICON_SIZE} />
      </button>
      <button
        aria-label={i18n.t.common.nextPage}
        class="btn-icon preset-tonal size-9"
        disabled={isLoading || page >= pages}
        onclick={(): void => onPage(page + 1)}
        title={i18n.t.common.nextPage}
        type="button"
      >
        <ChevronRight aria-hidden="true" size={ICON_SIZE} />
      </button>
    </div>
  </div>
</footer>
