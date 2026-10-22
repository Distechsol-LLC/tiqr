<script lang="ts">
  import type { Snippet } from 'svelte';

  import Sidebar from '@/components/Sidebar.svelte';

  type DashboardProps = {
    children: Snippet;
  };

  const { children }: DashboardProps = $props();
</script>

<div class="flex min-h-dvh flex-col md:flex-row">
  <Sidebar />
  <!-- On wide screens the page is exactly the viewport: the header bar stays put and the table
       scrolls beneath it -->
  <main class="flex min-w-0 flex-1 flex-col md:h-dvh">
    {@render children()}
  </main>
</div>
