<script lang="ts">
  import type { ClassValue } from 'svelte/elements';

  type LogoProps = {
    class?: ClassValue;
  };

  const { class: className }: LogoProps = $props();

  // public/ files are served under the app's base path
  const src = `${import.meta.env.BASE_URL}favicon.png`;
</script>

<!-- Decorative: every page names TiQR in its heading -->
<img
  alt=""
  class={['rounded-container select-none', className]}
  draggable="false"
  height="512"
  {src}
  width="512"
/>
