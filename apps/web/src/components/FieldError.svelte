<script lang="ts">
  import CircleAlert from '@lucide/svelte/icons/circle-alert';

  type FieldErrorProps = {
    id: string;
    error?: string;
  };

  const { id, error }: FieldErrorProps = $props();

  const ERROR_ICON_SIZE = 14;
</script>

<!-- Matches the message under FloatingInput, for fields it can't float a label in -->
{#if error}
  <p class="text-error-600-400 mt-1.5 flex items-center gap-1.5 text-sm" {id}>
    <CircleAlert aria-hidden="true" class="shrink-0" size={ERROR_ICON_SIZE} />
    {error}
  </p>
{/if}
