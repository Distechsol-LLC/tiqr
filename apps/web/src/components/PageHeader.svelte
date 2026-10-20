<script lang="ts">
  import type { Snippet } from 'svelte';

  type PageHeaderProps = {
    title: string;
    description?: string;
    actions?: Snippet;
  };

  const { title, description, actions }: PageHeaderProps = $props();
</script>

<svelte:head>
  <title>{title} · TiQR</title>
</svelte:head>

<header class="mb-6 flex flex-wrap items-end justify-between gap-4">
  <div class="space-y-1">
    <h1 class="h3">{title}</h1>
    {#if description}
      <p class="text-surface-600-400">{description}</p>
    {/if}
  </div>
  {#if actions}
    <div class="flex flex-wrap items-center gap-2">
      {@render actions()}
    </div>
  {/if}
</header>
