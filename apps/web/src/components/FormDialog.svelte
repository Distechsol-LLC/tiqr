<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import type { Snippet } from 'svelte';

  import Modal from '@/components/Modal.svelte';
  import { i18n } from '%/useLocale.svelte.ts';

  type FormDialogProps = {
    title: string;
    submitLabel: string;
    isOpen: boolean;
    isPending: boolean;
    isDestructive?: boolean;
    // Keeps the form from being sent while something it needs is missing
    isSubmitDisabled?: boolean;
    isNarrow?: boolean;
    onClose: () => void;
    onSubmit: (event: SubmitEvent) => void | Promise<void>;
    children: Snippet;
  };

  const {
    title,
    submitLabel,
    isOpen,
    isPending,
    isDestructive = false,
    isSubmitDisabled = false,
    isNarrow = false,
    onClose,
    onSubmit,
    children,
  }: FormDialogProps = $props();

  const ICON_SIZE = 18;

  const handleSubmit = (event: SubmitEvent): void => {
    event.preventDefault();

    if (!(isPending || isSubmitDisabled)) void onSubmit(event);
  };
</script>

<Modal ariaLabel={title} isClosable={!isPending} {isNarrow} {isOpen} {onClose}>
  <form
    aria-busy={isPending}
    class="card border-surface-200-800 bg-surface-50-950 space-y-5 border p-6 shadow-xl [--floating-label-notch:var(--color-surface-50-950)]"
    novalidate
    onsubmit={handleSubmit}
  >
    <h2 class="h4">{title}</h2>

    {@render children()}

    <footer class="flex justify-end gap-2 pt-2">
      <button
        class="btn preset-tonal h-11 min-w-36"
        disabled={isPending}
        onclick={onClose}
        type="button"
      >
        {i18n.t.common.cancel}
      </button>
      <button
        class={[
          'btn h-11 min-w-36',
          isDestructive ? 'preset-filled-error-500' : 'preset-filled-primary-500',
        ]}
        disabled={isPending || isSubmitDisabled}
        type="submit"
      >
        {#if isPending}
          <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
        {/if}
        {submitLabel}
      </button>
    </footer>
  </form>
</Modal>
