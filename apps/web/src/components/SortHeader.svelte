<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronUp from '@lucide/svelte/icons/chevron-up';

  import type { SortDirection } from '%/sort.ts';

  type SortHeaderProps = {
    label: string;
    // Null when another column, or none, is the one sorted
    direction: SortDirection | null;
    isEnd?: boolean;
    class?: string;
    onSort: () => void;
  };

  const ICON_SIZE = 14;
  const STROKE = 3;

  const { label, direction, isEnd = false, class: className, onSort }: SortHeaderProps = $props();
</script>

<th
  aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : undefined}
  class={[isEnd && 'text-right', className]}
>
  <button
    class="group inline-flex max-w-full cursor-pointer items-center gap-1.5 font-semibold hover:text-surface-950-50"
    onclick={onSort}
    title={label}
    type="button"
  >
    <span class="truncate">{label}</span>
    <!-- Both chevrons stay put; the one for the active direction lights up -->
    <span aria-hidden="true" class="flex shrink-0 flex-col -space-y-1.5">
      <ChevronUp
        class={direction === 'asc' ? 'text-primary-500' : 'opacity-30'}
        size={ICON_SIZE}
        strokeWidth={STROKE}
      />
      <ChevronDown
        class={direction === 'desc' ? 'text-primary-500' : 'opacity-30'}
        size={ICON_SIZE}
        strokeWidth={STROKE}
      />
    </span>
  </button>
</th>
