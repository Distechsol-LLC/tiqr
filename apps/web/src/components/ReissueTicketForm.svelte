<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import DateTimeField from '@/components/DateTimeField.svelte';
  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { reissueTicket } from '%/api.ts';
  import { nextMinute, toLocalInput } from '%/formatters.ts';
  import { formatMinor } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { mode } from '%/useMode.svelte.ts';
  import {
    GROUP_MAX,
    GROUP_MIN,
    type Ticket,
    editInputSchema,
    parseVisitorCount,
    priceFor,
  } from '$/tickets.ts';

  type ReissueTicketFormProps = {
    ticket: Ticket | null;
    onClose: () => void;
    onReissued: (ticket: Ticket) => void;
  };

  const DAY_END = 'T23:59';
  // Digits only; the range is checked by parseVisitorCount
  const COUNT_CHARS = /\D/g;

  const { ticket, onClose, onReissued }: ReissueTicketFormProps = $props();

  let validFrom = $state('');
  let validUntil = $state('');
  let visitorCount = $state('');
  // Whether the window had already ended when the dialog opened; its people are then fixed
  let isPast = $state(false);
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(
    editInputSchema.safeParse({ valid_from: validFrom, valid_until: validUntil })
  );
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Only a group's people can change; a badge or one-time ticket stays for one person, and a
  // group never shrinks to one
  const hasVisitors = $derived(!mode.isBadge && ticket?.usage_type === 'group');
  const count = $derived(parseVisitorCount(visitorCount));
  const countError = $derived(
    isSubmitted && hasVisitors && !isPast && count === null
      ? i18n.t.errors.groupSizeInvalid
      : undefined
  );
  // Only a changed number is sent, so a reissue that leaves it alone never trips the window check
  const changedCount = $derived(
    ticket && hasVisitors && !isPast && count !== null && count !== ticket.group_size
      ? count
      : undefined
  );
  // What the ticket cost, against what it will cost for the new number of people
  const reprice = $derived.by(() => {
    if (!(ticket?.currency && changedCount !== undefined)) return null;

    const before = priceFor(ticket, ticket.group_size);
    const after = priceFor(ticket, changedCount);

    if (before === null || after === null) return null;

    return { after, before, currency: ticket.currency, difference: after - before };
  });

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

      visitorCount = String(current.group_size);
      isPast = new Date(current.valid_until) < new Date();
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(ticket && validation.success && csrfToken) || countError) return;

    isPending = true;

    const result = await reissueTicket(csrfToken, ticket.id, {
      group_size: changedCount,
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
  <p>
    {ticket ? i18n.t.tickets.reissueConfirm(ticket.visitor_name || ticket.readable_serial) : ''}
  </p>

  {#if hasVisitors}
    <FloatingInput
      autocomplete="off"
      disabled={isPast}
      error={countError}
      id="reissue-visitors"
      inputmode="numeric"
      label={i18n.t.tickets.visitors}
      max={GROUP_MAX}
      min={GROUP_MIN}
      required
      strip={COUNT_CHARS}
      bind:value={visitorCount}
    />
    {#if isPast}
      <p class="text-surface-700-300 -mt-3 text-sm">{i18n.t.tickets.visitorsLocked}</p>
    {/if}
  {/if}

  {#if reprice}
    <!-- What the new number of people costs against what the ticket cost, at its own price -->
    <dl
      aria-live="polite"
      class="rounded-container border-surface-200-800 bg-surface-100-900 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 border px-4 py-3 text-sm tabular-nums"
    >
      <dt class="text-surface-700-300">{i18n.t.tickets.previousPrice}</dt>
      <dd class="text-right">{formatMinor(reprice.before, reprice.currency)}</dd>
      <dt class="text-surface-700-300">{i18n.t.tickets.newPrice}</dt>
      <dd class="text-right">{formatMinor(reprice.after, reprice.currency)}</dd>
      {#if reprice.difference !== 0}
        <dt
          class={[
            'font-semibold',
            reprice.difference > 0 ? 'text-success-700-300' : 'text-error-700-300',
          ]}
        >
          {reprice.difference > 0 ? i18n.t.tickets.priceUp : i18n.t.tickets.priceDown}
        </dt>
        <dd
          class={[
            'text-right font-semibold',
            reprice.difference > 0 ? 'text-success-700-300' : 'text-error-700-300',
          ]}
        >
          {reprice.difference > 0 ? '+' : '−'}{formatMinor(
            Math.abs(reprice.difference),
            reprice.currency
          )}
        </dd>
      {/if}
    </dl>
  {/if}

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
