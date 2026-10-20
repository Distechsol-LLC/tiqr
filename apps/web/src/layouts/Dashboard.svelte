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
  <main class="min-w-0 flex-1 p-4 md:p-8">
    {@render children()}
  </main>
</div>
