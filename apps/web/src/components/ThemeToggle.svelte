<script lang="ts">
  import Moon from '@lucide/svelte/icons/moon';
  import Sun from '@lucide/svelte/icons/sun';
  import type { ClassValue } from 'svelte/elements';

  import { i18n } from '%/useLocale.svelte.ts';
  import { theme } from '%/useTheme.svelte.ts';

  type ThemeToggleProps = {
    class?: ClassValue;
  };

  const { class: className }: ThemeToggleProps = $props();

  const label = $derived(theme.mode === 'dark' ? i18n.t.theme.light : i18n.t.theme.dark);
</script>

<button
  aria-label={label}
  class={['btn-icon btn-icon-2xl text-surface-950-50 hover:preset-tint-primary', className]}
  onclick={theme.toggle}
  title={i18n.t.theme.toggle}
  type="button"
>
  {#if theme.mode === 'dark'}
    <Sun aria-hidden="true" />
  {:else}
    <Moon aria-hidden="true" />
  {/if}
</button>
