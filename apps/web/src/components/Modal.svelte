<script lang="ts">
  import type { Snippet } from 'svelte';

  import { getFocus } from '%/getFocus.ts';

  type ModalProps = {
    children?: Snippet;
    isOpen?: boolean;
    isClosable?: boolean;
    // A smaller dialog, for a form with little in it
    isNarrow?: boolean;
    ariaLabel?: string;
    onClose?: () => void;
    onSubmit?: (event: SubmitEvent) => void | Promise<void>;
  };

  const {
    children,
    isOpen = true,
    isClosable = true,
    isNarrow = false,
    ariaLabel,
    onClose,
    onSubmit,
  }: ModalProps = $props();

  let dialog = $state<HTMLDivElement>();
  let overlay = $state<HTMLDivElement>();

  const focusTrap = getFocus({
    getContainer: () => dialog,
    isActive: () => isOpen,
  });

  const handleClose = (): void => {
    if (!isClosable) return;

    onClose?.();
  };

  const handleOverlayClick = (event: MouseEvent): void => {
    if (event.target === overlay) handleClose();
  };

  const handleKeydown = (event: KeyboardEvent): void => {
    if (!isOpen) return;

    // A popup inside the dialog (a date picker) takes Escape first and marks it handled
    if (event.key === 'Escape') {
      if (event.defaultPrevented) return;

      event.preventDefault();
      handleClose();
      return;
    }

    focusTrap.handleKeydown(event);
  };

  const handleSubmit = (event: SubmitEvent): void => {
    if (!onSubmit) return;

    event.preventDefault();
    void onSubmit(event);
  };

  $effect(() => {
    if (!isOpen) return;

    const previousBodyOverflow = document.body.style.overflow;

    document.body.style.overflow = 'hidden';

    const restoreFocus = focusTrap.trap();

    return (): void => {
      document.body.style.overflow = previousBodyOverflow;
      restoreFocus();
    };
  });
</script>

<svelte:window onclick={handleOverlayClick} onkeydown={handleKeydown} />

{#if isOpen}
  <div
    class="bg-surface-50-950/85 fixed inset-0 z-20 grid min-h-dvh place-items-center backdrop-blur-xs"
    role="presentation"
    bind:this={overlay}
  >
    <div
      aria-label={ariaLabel}
      aria-modal="true"
      class={['w-11/12 p-4', isNarrow ? 'max-w-sm' : 'max-w-lg']}
      onsubmit={handleSubmit}
      role="dialog"
      tabindex="-1"
      bind:this={dialog}
    >
      {@render children?.()}
    </div>
  </div>
{/if}
