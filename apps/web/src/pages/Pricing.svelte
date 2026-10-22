<script lang="ts">
  import Percent from '@lucide/svelte/icons/percent';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Tag from '@lucide/svelte/icons/tag';
  import { searchParams } from 'sv-router';

  import PageHeader from '@/components/PageHeader.svelte';
  import TicketTypesTable from '@/components/TicketTypesTable.svelte';
  import VisitorTypesTable from '@/components/VisitorTypesTable.svelte';
  import { i18n } from '%/useLocale.svelte.ts';

  type Section = 'ticket' | 'visitor';

  type Table = {
    create: () => void;
    reload: () => Promise<void>;
  };

  const ICON_SIZE = 18;
  const SECTIONS: Section[] = ['ticket', 'visitor'];
  const OPTIONS = { replace: true };

  // The section is in the URL, so a reload or a shared link shows the same table
  let section = $state<Section>(
    SECTIONS.find((option) => option === searchParams.get('section')) ?? 'ticket'
  );
  let table = $state<Table>();
  let isLoading = $state(true);

  // Each section's new button shows the icon of what it creates, not a plain plus
  const Icon = $derived(section === 'ticket' ? Tag : Percent);

  const choose = (next: Section): void => {
    if (next === section) return;

    // The other table starts on its first page, whatever page this one was on
    searchParams.delete('page', undefined, OPTIONS);

    if (next === 'ticket') searchParams.delete('section', undefined, OPTIONS);
    else searchParams.set('section', next, OPTIONS);

    section = next;
  };
</script>

<PageHeader description={i18n.t.pricing.description} title={i18n.t.pricing.title}>
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
      class={['btn h-11 preset-filled-primary-500', section === 'ticket' ? 'w-44' : 'w-36']}
      onclick={(): void => table?.create()}
      type="button"
    >
      <Icon aria-hidden="true" size={ICON_SIZE} />
      {section === 'ticket' ? i18n.t.ticketTypes.new : i18n.t.visitorTypes.new}
    </button>
  {/snippet}
  {#snippet toolbar()}
    <!-- As tall as the overview's period row, so the chips sit at the same height on both pages -->
    <div class="flex min-h-9 flex-wrap items-center justify-between gap-3">
      <fieldset class="flex flex-wrap gap-2">
        <legend class="sr-only">{i18n.t.pricing.tabs}</legend>
        {#each SECTIONS as option (option)}
          <button
            aria-pressed={section === option}
            class={['chip', section === option ? 'preset-filled-primary-500' : 'preset-tonal']}
            onclick={(): void => choose(option)}
            type="button"
          >
            {option === 'ticket' ? i18n.t.ticketTypes.tab : i18n.t.visitorTypes.tab}
          </button>
        {/each}
      </fieldset>
    </div>
  {/snippet}
</PageHeader>

<!-- Each table loads on mounting, so switching sections is a fresh load of the other -->
{#if section === 'ticket'}
  <TicketTypesTable bind:this={table} bind:isLoading />
{:else}
  <VisitorTypesTable bind:this={table} bind:isLoading />
{/if}
