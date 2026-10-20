<script lang="ts">
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import type { Snippet } from 'svelte';

  import Modal from '@/components/Modal.svelte';

  type FormDialogProps = {
    title: string;
    submitLabel: string;
    isOpen: boolean;
    isPending: boolean;
    onClose: () => void;
    onSubmit: (event: SubmitEvent) => void | Promise<void>;
    children: Snippet;
  };

  const { title, submitLabel, isOpen, isPending, onClose, onSubmit, children }: FormDialogProps =
    $props();

  const ICON_SIZE = 18;

  const handleSubmit = (event: SubmitEvent): void => {
    event.preventDefault();

    if (!isPending) void onSubmit(event);
  };
</script>

<Modal ariaLabel={title} isClosable={!isPending} {isOpen} {onClose}>
  <form
    aria-busy={isPending}
    class="card space-y-5 border border-surface-200-800 bg-surface-50-950 p-6 shadow-xl [--floating-label-notch:var(--color-surface-50-950)]"
    novalidate
    onsubmit={handleSubmit}
  >
    <h2 class="h4">{title}</h2>

    {@render children()}

    <footer class="flex justify-end gap-2 pt-2">
      <button class="btn preset-tonal" disabled={isPending} onclick={onClose} type="button">
        Cancel
      </button>
      <button class="btn preset-filled-primary-500" disabled={isPending} type="submit">
        {#if isPending}
          <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
        {/if}
        {submitLabel}
      </button>
    </footer>
  </form>
</Modal>
