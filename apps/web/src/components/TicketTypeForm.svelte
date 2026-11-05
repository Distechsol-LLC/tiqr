<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FloatingSelect from '@/components/FloatingSelect.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createTicketType, updateTicketType } from '%/api.ts';
  import { CURRENCY_LABELS, toPriceInput } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { branding } from '%/useBranding.svelte.ts';
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

  // Digits, with a point or comma for the pence
  const PRICE_CHARS = /[^\d.,]/g;

  let name = $state('');
  let price = $state('');
  let currency = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  // The currencies of the languages on offer, and the one being edited if it has fallen off them
  const currencies = $derived(
    editing && !branding.currencies.includes(editing.currency)
      ? [...branding.currencies, editing.currency]
      : branding.currencies
  );
  const validation = $derived(ticketTypeInputSchema.safeParse({ currency, name, price }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Each opening starts from the type being edited, or blank
  $effect(() => {
    if (!isOpen) return;

    untrack(() => {
      name = editing?.name ?? '';
      price = editing ? toPriceInput(editing.price_minor) : '';
      // With one currency on offer there is nothing to choose, so it is picked
      currency =
        editing?.currency ?? (branding.currencies.length === 1 ? branding.currencies[0] : '');
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    const fields = {
      currency: validation.data.currency,
      name: validation.data.name,
      price_minor: validation.data.price,
    };

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

  <div class="flex gap-3">
    <div class="w-32">
      <FloatingSelect
        error={fieldErrors.currency?.[0]}
        id="ticket-type-currency"
        label={i18n.t.ticketTypeForm.currency}
        labels={CURRENCY_LABELS}
        options={currencies}
        bind:value={currency}
      />
    </div>

    <div class="flex-1">
      <FloatingInput
        autocomplete="off"
        error={fieldErrors.price?.[0]}
        id="ticket-type-price"
        inputmode="decimal"
        label={i18n.t.ticketTypeForm.price}
        required
        strip={PRICE_CHARS}
        bind:value={price}
      />
    </div>
  </div>
</FormDialog>
