<script lang="ts">
  import Clock from '@lucide/svelte/icons/clock';
  import { onMount } from 'svelte';

  import ActiveHoursForm from '@/components/ActiveHoursForm.svelte';
  import { fetchActiveHours } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { ActiveHours } from '$/operations.ts';

  const ICON_SIZE = 18;

  const role = $derived(auth.session?.user.role ?? 'operator');
  // Operators can't set the hours, so the control is not offered to them
  const canSetHours = $derived(role !== 'operator');

  let activeHours = $state<ActiveHours | null>(null);
  let isEditing = $state(false);

  const load = async (): Promise<void> => {
    const result = await fetchActiveHours();

    if (result.ok) activeHours = result.data;
    else await notifyFailure(i18n.t.activeHours.notLoaded, result.error);
  };

  onMount(() => {
    if (canSetHours) void load();
  });
</script>

<!-- The hours passes may be made in, opened from a page header's actions -->
{#if canSetHours}
  <button
    aria-label={i18n.t.activeHours.button}
    class="btn-icon preset-tonal size-11"
    disabled={activeHours === null}
    onclick={(): void => {
      isEditing = true;
    }}
    title={i18n.t.activeHours.button}
    type="button"
  >
    <Clock aria-hidden="true" size={ICON_SIZE} />
  </button>

  {#if activeHours}
    <ActiveHoursForm
      current={activeHours}
      isOpen={isEditing}
      onClose={(): void => {
        isEditing = false;
      }}
      onSaved={(hours): void => {
        activeHours = hours;
      }}
    />
  {/if}
{/if}
