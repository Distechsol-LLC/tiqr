<script lang="ts">
  import { onMount } from 'svelte';

  import '/tailwind.config.css';
  import '@fontsource-variable/geist';
  import Modal from '@/components/Modal.svelte';
  import { modalHost } from '%/useModal.svelte.ts';
  import { useTooltip } from '%/useTooltip.ts';

  const activeModal = $derived(modalHost.current);

  onMount(useTooltip);
</script>

<div class="font-geist" title="test">
  TiQR

  {#if activeModal}
    <Modal isOpen={activeModal.isOpen} onClose={activeModal.close}>
      <activeModal.child onClose={activeModal.close} />
    </Modal>
  {/if}
</div>
