<script lang="ts">
  import type { ClassValue } from 'svelte/elements';

  import { branding } from '%/useBranding.svelte.ts';

  type LogoProps = {
    class?: ClassValue;
  };

  const { class: className }: LogoProps = $props();

  // public/ files are served under the app's base path; an install's own logo comes from the API
  const src = $derived(branding.logoSrc ?? `${import.meta.env.BASE_URL}favicon.png`);
</script>

<!-- Decorative: every page names the app in its heading -->
<img
  alt=""
  class={['rounded-container select-none', className]}
  draggable="false"
  height="512"
  {src}
  width="512"
/>
