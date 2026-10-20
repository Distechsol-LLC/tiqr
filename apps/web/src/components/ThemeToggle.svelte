<script lang="ts">
  import Moon from '@lucide/svelte/icons/moon';
  import Sun from '@lucide/svelte/icons/sun';
  import type { ClassValue } from 'svelte/elements';

  import { theme } from '%/useTheme.svelte.ts';

  type ThemeToggleProps = {
    class?: ClassValue;
  };

  // Floats in the corner of standalone pages; the sidebar places it inline instead
  const { class: className = 'fixed top-4 right-4 z-10 size-12' }: ThemeToggleProps = $props();

  const label = $derived(theme.mode === 'dark' ? 'Light' : 'Dark');
</script>

<button
  aria-label={label}
  class={['btn-icon btn-icon-2xl text-surface-950-50 hover:preset-tonal', className]}
  onclick={theme.toggle}
  title={label}
  type="button"
>
  {#if theme.mode === 'dark'}
    <Sun aria-hidden="true" />
  {:else}
    <Moon aria-hidden="true" />
  {/if}
</button>
