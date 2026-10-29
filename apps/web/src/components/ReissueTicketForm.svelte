<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import DateTimeField from '@/components/DateTimeField.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { reissueTicket } from '%/api.ts';
  import { nextMinute, toLocalInput } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type Ticket, editInputSchema } from '$/tickets.ts';

  type ReissueTicketFormProps = {
    ticket: Ticket | null;
    onClose: () => void;
    onReissued: (ticket: Ticket) => void;
  };

  const DAY_END = 'T23:59';

  const { ticket, onClose, onReissued }: ReissueTicketFormProps = $props();

  let validFrom = $state('');
  let validUntil = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(
    editInputSchema.safeParse({ valid_from: validFrom, valid_until: validUntil })
  );
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Keeps the old window while it still lies ahead; otherwise starts now and runs to the day's end
  $effect(() => {
    if (!ticket) return;

    const current = ticket;

    untrack(() => {
      const now = nextMinute();

      if (new Date(current.valid_until) > now) {
        validFrom = toLocalInput(new Date(current.valid_from), current.timezone);
        validUntil = toLocalInput(new Date(current.valid_until), current.timezone);
      } else {
        const start = toLocalInput(now, current.timezone);

        validFrom = start;
        validUntil = `${start.slice(0, start.indexOf('T'))}${DAY_END}`;
      }

      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(ticket && validation.success && csrfToken)) return;

    isPending = true;

    const result = await reissueTicket(csrfToken, ticket.id, {
      valid_from: validation.data.valid_from,
      valid_until: validation.data.valid_until,
    });

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.tickets.notReissued, result.error);
      return;
    }

    toaster.success({
      description: result.data.readable_serial,
      title: i18n.t.tickets.reissued,
    });
    onReissued(result.data);
    onClose();
  };
</script>

<FormDialog
  isOpen={ticket !== null}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.tickets.reissue}
  title={i18n.t.tickets.reissueFor(ticket?.readable_serial ?? i18n.t.assign.fallback)}
>
  <p>{ticket ? i18n.t.tickets.reissueConfirm(ticket.visitor_name) : ''}</p>

  <div class="grid gap-4">
    <DateTimeField
      error={fieldErrors.valid_from?.[0]}
      id="reissue-valid-from"
      label={i18n.t.ticketForm.validFrom}
      timeZone={ticket?.timezone}
      bind:value={validFrom}
    />
    <DateTimeField
      error={fieldErrors.valid_until?.[0]}
      id="reissue-valid-until"
      label={i18n.t.ticketForm.validUntil}
      min={validFrom}
      timeZone={ticket?.timezone}
      bind:value={validUntil}
    />
  </div>
</FormDialog>
