<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import DateTimeField from '@/components/DateTimeField.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { updateTicketWindow } from '%/api.ts';
  import { toLocalInput } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type Ticket, editInputSchema } from '$/tickets.ts';

  type EditTicketFormProps = {
    ticket: Ticket | null;
    onClose: () => void;
    onUpdated: (ticket: Ticket) => void;
  };

  const { ticket, onClose, onUpdated }: EditTicketFormProps = $props();

  let validFrom = $state('');
  let validUntil = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(
    editInputSchema.safeParse({
      valid_from: validFrom,
      valid_until: validUntil,
    })
  );
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Starts on the ticket's own window, read on the server's clock
  $effect(() => {
    if (!ticket) return;

    const current = ticket;

    untrack(() => {
      validFrom = toLocalInput(new Date(current.valid_from), current.timezone);
      validUntil = toLocalInput(new Date(current.valid_until), current.timezone);
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(ticket && validation.success && csrfToken)) return;

    const { data } = validation;
    const windowChanged =
      data.valid_from !== toLocalInput(new Date(ticket.valid_from), ticket.timezone) ||
      data.valid_until !== toLocalInput(new Date(ticket.valid_until), ticket.timezone);

    if (!windowChanged) {
      onClose();
      return;
    }

    isPending = true;

    const result = await updateTicketWindow(csrfToken, ticket.id, {
      valid_from: data.valid_from,
      valid_until: data.valid_until,
    });

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.tickets.notUpdated, result.error);
      return;
    }

    toaster.success({
      description: result.data.readable_serial,
      title: i18n.t.tickets.updated,
    });
    onUpdated(result.data);
    onClose();
  };
</script>

<FormDialog
  isOpen={ticket !== null}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.tickets.save}
  title={i18n.t.tickets.editFor(ticket?.readable_serial ?? i18n.t.assign.fallback)}
>
  <div class="grid gap-4">
    <DateTimeField
      error={fieldErrors.valid_from?.[0]}
      id="edit-valid-from"
      label={i18n.t.ticketForm.validFrom}
      timeZone={ticket?.timezone}
      bind:value={validFrom}
    />
    <DateTimeField
      error={fieldErrors.valid_until?.[0]}
      id="edit-valid-until"
      label={i18n.t.ticketForm.validUntil}
      min={validFrom}
      timeZone={ticket?.timezone}
      bind:value={validUntil}
    />
  </div>
</FormDialog>
