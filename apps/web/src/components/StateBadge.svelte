<script lang="ts">
  import { i18n } from '%/useLocale.svelte.ts';
  import type { TicketState } from '$/tickets.ts';

  type StateBadgeProps = {
    state: TicketState;
  };

  const { state }: StateBadgeProps = $props();

  const PRESETS: Record<TicketState, string> = {
    expired: 'badge-surface',
    issued: 'badge-primary',
    passed: 'badge-success',
    revoked: 'badge-error',
  };
</script>

<!-- A flex box isn't cut with an ellipsis by its cell, so the label inside is -->
<span class={['badge-status max-w-full', PRESETS[state]]}>
  <span class="truncate">{i18n.t.states[state]}</span>
</span>
