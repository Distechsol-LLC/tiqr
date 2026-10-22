<script lang="ts">
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Tag from '@lucide/svelte/icons/tag';

  import PageHeader from '@/components/PageHeader.svelte';
  import TicketTypesTable from '@/components/TicketTypesTable.svelte';
  import { i18n } from '%/useLocale.svelte.ts';

  type Table = {
    create: () => void;
    reload: () => Promise<void>;
  };

  const ICON_SIZE = 18;

  let table = $state<Table>();
  let isLoading = $state(true);
</script>

<PageHeader description={i18n.t.ticketTypes.description} title={i18n.t.ticketTypes.caption}>
  {#snippet actions()}
    <button
      aria-label={i18n.t.common.refresh}
      class="btn-icon size-11 preset-tonal"
      disabled={isLoading}
      onclick={(): void => {
        void table?.reload();
      }}
      title={i18n.t.common.refresh}
      type="button"
    >
      <RefreshCw
        aria-hidden="true"
        class={isLoading ? 'animate-spin' : undefined}
        size={ICON_SIZE}
      />
    </button>
    <button
      class="btn h-11 min-w-44 preset-filled-primary-500"
      onclick={(): void => table?.create()}
      type="button"
    >
      <Tag aria-hidden="true" size={ICON_SIZE} />
      {i18n.t.ticketTypes.new}
    </button>
  {/snippet}
</PageHeader>

<TicketTypesTable bind:this={table} bind:isLoading />
