<script lang="ts">
  import type { Snippet } from 'svelte';

  type PageHeaderProps = {
    title: string;
    description?: string;
    actions?: Snippet;
    // A second row inside the bar, for filters and search
    toolbar?: Snippet;
  };

  const { title, description, actions, toolbar }: PageHeaderProps = $props();
</script>

<svelte:head>
  <title>{title} · TiQR</title>
</svelte:head>

<!-- A bar across the top of the page, colored like the sidebar; the table below fills the rest -->
<header
  class="shrink-0 space-y-4 border-surface-200-800 border-b bg-surface-100-900 p-4 md:px-8 md:py-5"
>
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div class="space-y-1">
      <h1 class="h4">{title}</h1>
      {#if description}
        <p class="text-sm text-surface-600-400">{description}</p>
      {/if}
    </div>
    {#if actions}
      <div class="flex flex-wrap items-center gap-2">
        {@render actions()}
      </div>
    {/if}
  </div>
  {#if toolbar}
    {@render toolbar()}
  {/if}
</header>
