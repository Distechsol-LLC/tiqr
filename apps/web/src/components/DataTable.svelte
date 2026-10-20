<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import type { Snippet } from 'svelte';

  type DataTableProps = {
    caption: string;
    columns: number;
    isEmpty: boolean;
    isLoading: boolean;
    emptyMessage: string;
    head: Snippet;
    children: Snippet;
  };

  const { caption, columns, isEmpty, isLoading, emptyMessage, head, children }: DataTableProps =
    $props();
</script>

<div
  aria-busy={isLoading}
  class="card table-wrap border border-surface-200-800 bg-surface-50-950 shadow-sm"
>
  <table class="table">
    <caption class="sr-only">
      {caption}
    </caption>
    <thead class="bg-surface-100-900">
      <tr>
        {@render head()}
      </tr>
    </thead>
    <tbody class="[&>tr]:hover:bg-surface-100-900/60">
      {#if isLoading && isEmpty}
        <tr>
          <td class="py-10 text-center text-surface-600-400" colspan={columns}>
            <LoaderCircle aria-label="Loading" class="mx-auto animate-spin" />
          </td>
        </tr>
      {:else if isEmpty}
        <tr>
          <td class="py-10 text-center text-surface-600-400" colspan={columns}>{emptyMessage}</td>
        </tr>
      {:else}
        {@render children()}
      {/if}
    </tbody>
  </table>
</div>
