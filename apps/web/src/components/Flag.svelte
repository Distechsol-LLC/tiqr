<script lang="ts">
  import type { Locale } from '@/config/locales.ts';

  type FlagProps = {
    code: Locale;
  };

  const { code }: FlagProps = $props();
</script>

<!-- Drawn inline: emoji flags fall back to bare letters wherever the system font lacks them -->
<svg
  aria-hidden="true"
  class="me-3 h-4 w-6 shrink-0 rounded-xs"
  viewBox="0 0 24 16"
  xmlns="http://www.w3.org/2000/svg"
>
  {#if code === 'en'}
    <rect fill="#012169" height="16" width="24" />
    <path d="M0 0L24 16M24 0L0 16" stroke="#fff" stroke-width="3.2" />
    <path d="M0 0L24 16M24 0L0 16" stroke="#C8102E" stroke-width="1.2" />
    <path d="M12 0V16M0 8H24" stroke="#fff" stroke-width="5.3" />
    <path d="M12 0V16M0 8H24" stroke="#C8102E" stroke-width="3.2" />
  {:else if code === 'ru'}
    <rect fill="#fff" height="16" width="24" />
    <rect fill="#0039A6" height="5.34" width="24" y="5.33" />
    <rect fill="#D52B1E" height="5.34" width="24" y="10.66" />
  {:else}
    <rect fill="#00B5E2" height="5.34" width="24" />
    <rect fill="#EF3340" height="5.34" width="24" y="5.33" />
    <rect fill="#509E2F" height="5.34" width="24" y="10.66" />
    <circle cx="11.4" cy="8" fill="#fff" r="2.1" />
    <circle cx="12" cy="8" fill="#EF3340" r="1.7" />
    <path
      d="M14.2 6.9L14.5 7.7L15.3 7.7L14.7 8.2L14.9 9L14.2 8.5L13.5 9L13.7 8.2L13.1 7.7L13.9 7.7Z"
      fill="#fff"
    />
  {/if}
</svg>
