<script lang="ts">
  import Clock from '@lucide/svelte/icons/clock';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Tag from '@lucide/svelte/icons/tag';
  import { onMount } from 'svelte';

  import ActiveHoursForm from '@/components/ActiveHoursForm.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import TicketTypesTable from '@/components/TicketTypesTable.svelte';
  import { fetchActiveHours } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { ActiveHours } from '$/operations.ts';

  type Table = {
    create: () => void;
    reload: () => Promise<void>;
  };

  const ICON_SIZE = 18;

  const role = $derived(auth.session?.user.role ?? 'operator');
  // Operators can't set the hours, so the control is not offered to them
  const canSetHours = $derived(role !== 'operator');

  let table = $state<Table>();
  let isLoading = $state(true);
  let activeHours = $state<ActiveHours | null>(null);
  let isEditingHours = $state(false);

  const loadActiveHours = async (): Promise<void> => {
    const result = await fetchActiveHours();

    if (result.ok) activeHours = result.data;
    else await notifyFailure(i18n.t.activeHours.notLoaded, result.error);
  };

  onMount(() => {
    if (canSetHours) void loadActiveHours();
  });
</script>

<PageHeader description={i18n.t.ticketTypes.description} title={i18n.t.ticketTypes.caption}>
  {#snippet actions()}
    <button
      aria-label={i18n.t.common.refresh}
      class="btn-icon preset-tonal size-11"
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
    {#if canSetHours}
      <button
        aria-label={i18n.t.activeHours.button}
        class="btn-icon preset-tonal size-11"
        disabled={activeHours === null}
        onclick={(): void => {
          isEditingHours = true;
        }}
        title={i18n.t.activeHours.button}
        type="button"
      >
        <Clock aria-hidden="true" size={ICON_SIZE} />
      </button>
    {/if}
    <button
      class="btn preset-filled-primary-500 h-11 min-w-44"
      onclick={(): void => table?.create()}
      type="button"
    >
      <Tag aria-hidden="true" size={ICON_SIZE} />
      {i18n.t.ticketTypes.new}
    </button>
  {/snippet}
</PageHeader>

<TicketTypesTable bind:this={table} bind:isLoading />

{#if canSetHours && activeHours}
  <ActiveHoursForm
    current={activeHours}
    isOpen={isEditingHours}
    onClose={(): void => {
      isEditingHours = false;
    }}
    onSaved={(hours): void => {
      activeHours = hours;
    }}
  />
{/if}
