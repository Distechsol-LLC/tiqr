<script lang="ts">
  import Moon from '@lucide/svelte/icons/moon';
  import Sun from '@lucide/svelte/icons/sun';

  import { theme } from '%/useTheme.svelte.ts';

  const label = $derived(theme.mode === 'dark' ? 'Light' : 'Dark');
</script>

<button
  aria-label={label}
  class="btn-icon btn-icon-2xl fixed top-4 right-4 z-10 size-12 text-surface-950-50 hover:preset-tonal"
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
