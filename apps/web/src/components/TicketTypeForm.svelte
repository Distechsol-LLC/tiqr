<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createTicketType, updateTicketType } from '%/api.ts';
  import { toPriceInput } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type TicketType, ticketTypeInputSchema } from '$/catalog.ts';

  type TicketTypeFormProps = {
    // The type being changed; null makes a new one
    editing: TicketType | null;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (ticketType: TicketType) => void;
  };

  const { editing, isOpen, onClose, onSaved }: TicketTypeFormProps = $props();

  let name = $state('');
  let price = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(ticketTypeInputSchema.safeParse({ name, price }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Each opening starts from the type being edited, or blank
  $effect(() => {
    if (!isOpen) return;

    untrack(() => {
      name = editing?.name ?? '';
      price = editing ? toPriceInput(editing.price_minor) : '';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    const fields = { name: validation.data.name, price_minor: validation.data.price };

    isPending = true;

    const result = editing
      ? await updateTicketType(csrfToken, editing.id, fields)
      : await createTicketType(csrfToken, fields);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(
        editing ? i18n.t.ticketTypeForm.notUpdated : i18n.t.ticketTypeForm.notCreated,
        result.error
      );
      return;
    }

    toaster.success({
      description: result.data.name,
      title: editing ? i18n.t.ticketTypeForm.updated : i18n.t.ticketTypeForm.created,
    });
    onSaved(result.data);
    onClose();
  };
</script>

<FormDialog
  {isOpen}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={editing ? i18n.t.common.save : i18n.t.common.create}
  title={editing ? i18n.t.ticketTypeForm.titleEdit : i18n.t.ticketTypeForm.titleNew}
>
  <FloatingInput
    autocomplete="off"
    error={fieldErrors.name?.[0]}
    id="ticket-type-name"
    label={i18n.t.ticketTypeForm.name}
    required
    bind:value={name}
  />

  <FloatingInput
    autocomplete="off"
    error={fieldErrors.price?.[0]}
    id="ticket-type-price"
    inputmode="decimal"
    label={i18n.t.ticketTypeForm.price}
    required
    bind:value={price}
  />
</FormDialog>
