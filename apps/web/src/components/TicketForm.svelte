<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FieldError from '@/components/FieldError.svelte';
  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createTicket } from '%/api.ts';
  import { USAGE_LABELS, nextMinute, toLocalInput } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { type Ticket, type UsageType, ticketInputSchema, usageTypeSchema } from '$/tickets.ts';

  type TicketFormProps = {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (ticket: Ticket) => void;
  };

  const { isOpen, onClose, onCreated }: TicketFormProps = $props();

  const DAY_END = 'T23:59';

  let visitorName = $state('');
  let visitorType = $state('');
  let validFrom = $state('');
  let validUntil = $state('');
  let usageType = $state<UsageType>('one_time');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(
    ticketInputSchema.safeParse({
      usage_type: usageType,
      valid_from: validFrom,
      valid_until: validUntil,
      visitor_name: visitorName,
      visitor_type: visitorType,
    })
  );

  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Each opening starts fresh: from the next minute until the end of that day, on the server's clock
  $effect(() => {
    if (!isOpen) return;

    // Only opening resets the form, not the config arriving while it's open
    untrack(() => {
      const timezone = config.current?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
      const start = toLocalInput(nextMinute(), timezone);

      visitorName = '';
      visitorType = '';
      validFrom = start;
      validUntil = `${start.slice(0, start.indexOf('T'))}${DAY_END}`;
      usageType = 'one_time';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    isPending = true;

    const result = await createTicket(csrfToken, validation.data);

    isPending = false;

    if (!result.ok) {
      await notifyFailure('Ticket not created', result.error);
      return;
    }

    toaster.success({
      description: `${result.data.readable_serial} for ${result.data.visitor_name}`,
      title: 'Ticket created',
    });
    onCreated(result.data);
    onClose();
  };
</script>

<FormDialog
  {isOpen}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel="Create"
  title="New ticket"
>
  <FloatingInput
    autocomplete="off"
    error={fieldErrors.visitor_name?.[0]}
    id="visitor-name"
    label="Visitor name"
    required
    bind:value={visitorName}
  />

  <FloatingInput
    autocomplete="off"
    error={fieldErrors.visitor_type?.[0]}
    id="visitor-type"
    label="Visitor type"
    required
    bind:value={visitorType}
  />

  <div class="grid gap-4">
    <label class="label">
      <span class="label-text">Valid from</span>
      <input
        aria-describedby={fieldErrors.valid_from ? 'valid-from-error' : undefined}
        aria-invalid={fieldErrors.valid_from ? 'true' : undefined}
        class="input aria-invalid:ring-error-500"
        required
        type="datetime-local"
        bind:value={validFrom}
      />
      <FieldError error={fieldErrors.valid_from?.[0]} id="valid-from-error" />
    </label>

    <label class="label">
      <span class="label-text">Valid until</span>
      <input
        aria-describedby={fieldErrors.valid_until ? 'valid-until-error' : undefined}
        aria-invalid={fieldErrors.valid_until ? 'true' : undefined}
        class="input aria-invalid:ring-error-500"
        min={validFrom}
        required
        type="datetime-local"
        bind:value={validUntil}
      />
      <FieldError error={fieldErrors.valid_until?.[0]} id="valid-until-error" />
    </label>
  </div>

  {#if config.current}
    <p class="-mt-2 text-surface-600-400 text-xs">Times are in {config.current.timezone}.</p>
  {/if}

  <fieldset class="space-y-2">
    <legend class="label-text">Usage</legend>
    <div class="flex gap-6">
      {#each usageTypeSchema.options as option (option)}
        <label class="flex items-center gap-2">
          <input
            class="radio"
            name="usage-type"
            type="radio"
            value={option}
            bind:group={usageType}
          />
          {USAGE_LABELS[option]}
        </label>
      {/each}
    </div>
  </fieldset>
</FormDialog>
