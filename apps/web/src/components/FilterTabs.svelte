<script generics="T extends string" lang="ts">
  type FilterTabsProps<T extends string> = {
    legend: string;
    options: T[];
    selected: T;
    label: (option: T) => string;
    onpick: (option: T) => void;
  };

  const { legend, options, selected, label, onpick }: FilterTabsProps<T> = $props();
</script>

<!-- Tabs of the table below: they hang over the header's bottom padding and border, so the picked
     one joins the table, and run out to the sidebar's edge on the left. The margins match the
     header's padding (p-4, md:px-8, md:py-5) -->
<fieldset class="-mb-4 -ml-4 flex translate-y-px flex-wrap self-end md:-mb-5 md:-ml-8">
  <legend class="sr-only">{legend}</legend>
  {#each options as option (option)}
    <button
      aria-pressed={selected === option}
      class="filter-tab"
      onclick={(): void => onpick(option)}
      type="button"
    >
      {label(option)}
    </button>
  {/each}
</fieldset>
