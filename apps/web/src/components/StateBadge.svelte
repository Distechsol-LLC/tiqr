<script lang="ts">
  import { STATE_LABELS } from '%/formatters.ts';
  import type { TicketState } from '$/tickets.ts';

  type StateBadgeProps = {
    state: TicketState;
  };

  const { state }: StateBadgeProps = $props();

  const PRESETS: Record<TicketState, string> = {
    expired: 'preset-tonal-surface',
    issued: 'preset-tonal-primary',
    passed: 'preset-tonal-success',
  };
</script>

<span class={['badge', PRESETS[state]]}>{STATE_LABELS[state]}</span>
