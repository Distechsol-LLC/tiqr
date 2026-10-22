<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import type { Component, Snippet } from 'svelte';

  import { i18n } from '%/useLocale.svelte.ts';

  type DataTableProps = {
    caption: string;
    columns: number;
    // Below this the table scrolls sideways, rather than squeezing the column without a set width
    minWidth: string;
    isEmpty: boolean;
    isLoading: boolean;
    emptyMessage: string;
    // Sits above the empty message
    emptyIcon: Component;
    head: Snippet;
    children: Snippet;
  };

  const EMPTY_ICON_SIZE = 40;
  const EMPTY_ICON_STROKE = 1.5;

  const {
    caption,
    columns,
    minWidth,
    isEmpty,
    isLoading,
    emptyMessage,
    emptyIcon: EmptyIcon,
    head,
    children,
  }: DataTableProps = $props();
</script>

<!-- Fills the page below the header bar, edge to edge; the outer cells line up with the bar's padding -->
<div
  aria-busy={isLoading}
  class="table-wrap min-h-0 flex-1 bg-[light-dark(white,var(--color-surface-950))]"
>
  <!-- Empty, the table fills the area and its single row takes the space the head leaves, so the
       empty message sits in the middle of the page. The layout is fixed: columns keep the widths
       the head sets whatever the language, and text that doesn't fit ends in an ellipsis. Borders
       sit on the cells instead of collapsing into the table's, so the sticky head keeps its own;
       collapsed, Firefox paints the head's shade over them -->
  <table
    class={[
      isEmpty && 'h-full',
      'table table-fixed border-separate border-spacing-0 [&_:is(th,td)]:truncate [&_td>p]:truncate [&_:is(th,td)]:border-b [&_:is(th,td)]:[border-color:light-dark(var(--color-surface-200),var(--color-surface-800))] [&_:is(th,td):not(:first-child)]:border-s [&_:is(th,td)]:px-4 [&_:is(th,td)]:py-3 [&_:is(th,td):first-child]:ps-4 md:[&_:is(th,td):first-child]:ps-8 [&_:is(th,td):last-child]:pe-4 md:[&_:is(th,td):last-child]:pe-8',
    ]}
    style:min-width={minWidth}
  >
    <caption class="sr-only">
      {caption}
    </caption>
    <!-- The head wears the sidebar's panel shade -->
    <thead
      class="sticky top-0 z-10 bg-surface-100-900 text-surface-700-300 [&_th]:font-semibold [&_th]:text-sm"
    >
      <tr>
        {@render head()}
      </tr>
    </thead>
    <!-- Empty or loading, the lone row is a message, not a record, so it doesn't highlight -->
    <tbody
      class={[
        '[--tint-base:var(--color-surface-50-950)] [&>tr]:even:bg-surface-100-900',
        !isEmpty && '[&>tr]:hover:bg-surface-200-800/70',
      ]}
    >
      {#if isLoading && isEmpty}
        <tr class="h-full">
          <td class="py-36 text-center text-surface-600-400" colspan={columns}>
            <LoaderCircle aria-label={i18n.t.common.loading} class="mx-auto animate-spin" />
          </td>
        </tr>
      {:else if isEmpty}
        <tr class="h-full">
          <td class="py-36 text-center text-surface-600-400" colspan={columns}>
            <EmptyIcon
              aria-hidden="true"
              class="mx-auto mb-3 opacity-60"
              size={EMPTY_ICON_SIZE}
              strokeWidth={EMPTY_ICON_STROKE}
            />
            {emptyMessage}
          </td>
        </tr>
      {:else}
        {@render children()}
      {/if}
    </tbody>
  </table>
</div>
