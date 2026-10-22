<script lang="ts">
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import TicketsIcon from '@lucide/svelte/icons/tickets';
  import { type Component, untrack } from 'svelte';
  import { z } from 'zod';

  import DateTimeField from '@/components/DateTimeField.svelte';
  import FloatingInput from '@/components/FloatingInput.svelte';
  import FloatingSelect from '@/components/FloatingSelect.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createTicket } from '%/api.ts';
  import { nextMinute, toLocalInput } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import {
    type Ticket,
    type UsageType,
    ticketInputSchema,
    usageTypeSchema,
    visitorTypeOptions,
  } from '$/tickets.ts';

  type TicketFormProps = {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (ticket: Ticket) => void;
  };

  const { isOpen, onClose, onCreated }: TicketFormProps = $props();

  const DAY_END = 'T23:59';
  const USAGE_ICON_SIZE = 16;
  const USAGE_ICONS: Record<UsageType, Component> = {
    multi_use: TicketsIcon,
    one_time: TicketIcon,
  };
  const USAGE_OPTIONS = usageTypeSchema.options.map((value) => ({
    Icon: USAGE_ICONS[value],
    value,
  }));

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
      await notifyFailure(i18n.t.ticketForm.notCreated, result.error);
      return;
    }

    toaster.success({
      description: i18n.t.ticketForm.createdFor(
        result.data.readable_serial,
        result.data.visitor_name
      ),
      title: i18n.t.ticketForm.created,
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
  submitLabel={i18n.t.common.create}
  title={i18n.t.ticketForm.title}
>
  <FloatingInput
    autocomplete="off"
    error={fieldErrors.visitor_name?.[0]}
    id="visitor-name"
    label={i18n.t.ticketForm.visitorName}
    required
    bind:value={visitorName}
  />

  <FloatingSelect
    error={fieldErrors.visitor_type?.[0]}
    id="visitor-type"
    label={i18n.t.ticketForm.visitorType}
    options={visitorTypeOptions}
    bind:value={visitorType}
  />

  <div class="grid gap-4">
    <DateTimeField
      error={fieldErrors.valid_from?.[0]}
      id="valid-from"
      label={i18n.t.ticketForm.validFrom}
      timeZone={config.current?.timezone}
      bind:value={validFrom}
    />

    <DateTimeField
      error={fieldErrors.valid_until?.[0]}
      id="valid-until"
      label={i18n.t.ticketForm.validUntil}
      min={validFrom}
      timeZone={config.current?.timezone}
      bind:value={validUntil}
    />
  </div>

  <fieldset class="space-y-2">
    <legend class="label-text">{i18n.t.ticketForm.usage}</legend>
    <!-- Still radios underneath, for arrow keys and the form, but shown as a pair of buttons -->
    <div class="grid grid-cols-2 gap-2">
      {#each USAGE_OPTIONS as { Icon, value: option } (option)}
        <label
          class={[
            'btn h-12 cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-primary-500 has-focus-visible:outline-offset-2',
            usageType === option ? 'preset-filled-primary-500' : 'preset-tonal',
          ]}
        >
          <input
            class="sr-only"
            name="usage-type"
            type="radio"
            value={option}
            bind:group={usageType}
          />
          <Icon aria-hidden="true" size={USAGE_ICON_SIZE} />
          {i18n.t.usage[option]}
        </label>
      {/each}
    </div>
  </fieldset>
</FormDialog>
