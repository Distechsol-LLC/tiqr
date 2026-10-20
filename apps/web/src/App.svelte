<script lang="ts">
  import { Toast } from '@skeletonlabs/skeleton-svelte';
  import { Router } from 'sv-router';
  import { onMount } from 'svelte';

  import '/tailwind.config.css';
  import '@fontsource-variable/geist';
  import '@/router.ts';
  import Modal from '@/components/Modal.svelte';
  import ThemeToggle from '@/components/ThemeToggle.svelte';
  import { toaster } from '%/toaster.ts';
  import { modalHost } from '%/useModal.svelte.ts';
  import { useTooltip } from '%/useTooltip.ts';

  const activeModal = $derived(modalHost.current);

  onMount(useTooltip);
</script>

<ThemeToggle />
<Router />

{#if activeModal}
  <Modal {...activeModal.settings} isOpen={activeModal.isOpen} onClose={activeModal.close}>
    <activeModal.child onClose={activeModal.close} />
  </Modal>
{/if}

<Toast.Group {toaster}>
  {#snippet children(
    toast
  )}
    <Toast {toast}>
      <Toast.Message>
        <Toast.Title>{toast.title}</Toast.Title>
        <Toast.Description>{toast.description}</Toast.Description>
      </Toast.Message>
      <Toast.CloseTrigger />
    </Toast>
  {/snippet}
</Toast.Group>
