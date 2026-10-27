<script lang="ts">
  import { i18n } from '%/useLocale.svelte.ts';

  type ActionsHeaderProps = {
    // The most icon buttons a row shows
    count: number;
  };

  const BUTTON_REM = 2.25;
  const GAP_REM = 0.25;

  const { count }: ActionsHeaderProps = $props();
</script>

<!-- A fixed table can't fit a column to its buttons, so it's sized to them; the width leaves out
     the padding, which differs at the table's edge -->
<th class="box-content" data-fixed style:width="{count * BUTTON_REM + (count - 1) * GAP_REM}rem">
  <span class="sr-only">{i18n.t.common.actions}</span>
</th>
