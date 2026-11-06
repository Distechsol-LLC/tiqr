<script lang="ts">
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import TicketsIcon from '@lucide/svelte/icons/tickets';
  import { type Component, untrack } from 'svelte';

  import DateTimeField from '@/components/DateTimeField.svelte';
  import FloatingInput from '@/components/FloatingInput.svelte';
  import FloatingSelect from '@/components/FloatingSelect.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import {
    createTicket,
    fetchActiveHours,
    fetchAllTicketTypes,
    fetchAllVisitorTypes,
  } from '%/api.ts';
  import { nextMinute, toLocalInput } from '%/formatters.ts';
  import { discountedMinor, formatMinor } from '%/money.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { config } from '%/useConfig.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { mode } from '%/useMode.svelte.ts';
  import type { TicketType, VisitorType } from '$/catalog.ts';
  import { type ActiveHours, isWithinHours } from '$/operations.ts';
  import {
    GROUP_MAX,
    GROUP_MIN,
    TICKET_USAGES,
    type Ticket,
    type UsageType,
    parseTicketInput,
  } from '$/tickets.ts';

  type TicketFormProps = {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (ticket: Ticket) => void;
  };

  const { isOpen, onClose, onCreated }: TicketFormProps = $props();

  const DAY_END = 'T23:59';
  const USAGE_ICON_SIZE = 16;
  // What a ticket may admit; a badge is always multi-use, so it offers no choice
  const USAGE_ICONS: Record<(typeof TICKET_USAGES)[number], Component> = {
    group: TicketsIcon,
    one_time: TicketIcon,
  };
  const USAGE_OPTIONS = TICKET_USAGES.map((value) => ({ Icon: USAGE_ICONS[value], value }));
  // Digits only; the range is checked in the schema
  const GROUP_CHARS = /\D/g;

  let visitorName = $state('');
  let visitorType = $state('');
  let visitorSubtype = $state('');
  let ticketType = $state('');
  let ticketTypes = $state<TicketType[]>([]);
  let visitorTypes = $state<VisitorType[]>([]);
  let activeHours = $state<ActiveHours | null>(null);
  let validFrom = $state('');
  let validUntil = $state('');
  let usageType = $state<UsageType>('one_time');
  let groupSize = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);
  // Known only once the visitor types have loaded; a failed load says nothing about there being none
  let hasNoVisitorTypes = $state(false);
  // Likewise for ticket types: a ticket is priced by one, so it cannot be made without
  let hasNoTicketTypes = $state(false);

  const isBadge = $derived(mode.isBadge);
  const validation = $derived(
    parseTicketInput(mode.current, {
      group_size: groupSize,
      ticket_type: ticketType,
      usage_type: isBadge ? 'multi_use' : usageType,
      valid_from: validFrom,
      valid_until: validUntil,
      visitor_name: visitorName,
      visitor_subtype: visitorSubtype,
      visitor_type: visitorType,
    })
  );

  const fieldErrors = $derived(isSubmitted && !validation.ok ? validation.errors : {});

  // Badges have no ticket types or prices
  const ticketTypeOptions = $derived(isBadge ? [] : ticketTypes.map((type) => type.name));
  // A ticket needs a ticket type, since that is what prices it
  const ticketTypeError = $derived(
    isSubmitted && !isBadge && !hasNoTicketTypes && !ticketType
      ? i18n.t.errors.ticketTypeRequired
      : undefined
  );
  const isBlocked = $derived(hasNoVisitorTypes || (!isBadge && hasNoTicketTypes));
  const priced = $derived(
    isBadge ? undefined : ticketTypes.find((type) => type.name === ticketType)
  );
  // A ticket is for a subtype of its visitor type, so only types that have one are offered
  const visitorTypeOptions = $derived(
    (isBadge ? visitorTypes : visitorTypes.filter((type) => type.subtypes.length > 0)).map(
      (type) => type.name
    )
  );
  const subtypes = $derived(
    isBadge ? [] : (visitorTypes.find((type) => type.name === visitorType)?.subtypes ?? [])
  );
  const discount = $derived(
    subtypes.find((subtype) => subtype.name === visitorSubtype)?.discount_percent ?? 0
  );
  // What each person pays: the type's price less the visitor subtype's discount
  const perPerson = $derived(priced ? discountedMinor(priced.price_minor, discount) : 0);
  // How many people the price is paid for: one, or the group's size once it is a valid one
  const people = $derived.by((): number => {
    if (isBadge || usageType !== 'group') return 1;

    const size = Number(groupSize);

    return Number.isInteger(size) && size >= GROUP_MIN && size <= GROUP_MAX ? size : 0;
  });
  // The hours tickets may be made in, when a limit is set; the server enforces them on submit
  const limit = $derived(
    activeHours?.start && activeHours.end
      ? { end: activeHours.end, start: activeHours.start }
      : null
  );
  // The time pickers grey out the times outside those hours
  const allowsTime = $derived(
    limit ? (clock: string): boolean => isWithinHours(limit, clock) : undefined
  );

  const loadCatalog = async (): Promise<void> => {
    const [ticketResult, visitorResult, hoursResult] = await Promise.all([
      // A badge has no ticket type to pick
      isBadge ? Promise.resolve({ data: [], ok: true as const }) : fetchAllTicketTypes(),
      fetchAllVisitorTypes(),
      fetchActiveHours(),
    ]);

    if (ticketResult.ok) {
      ticketTypes = ticketResult.data;
      hasNoTicketTypes = !isBadge && ticketResult.data.length === 0;
    } else await notifyFailure(i18n.t.ticketForm.catalogNotLoaded, ticketResult.error);

    if (visitorResult.ok) {
      visitorTypes = visitorResult.data;
      hasNoVisitorTypes = isBadge
        ? visitorResult.data.length === 0
        : visitorResult.data.every((type) => type.subtypes.length === 0);
    } else await notifyFailure(i18n.t.ticketForm.catalogNotLoaded, visitorResult.error);

    if (hoursResult.ok) activeHours = hoursResult.data;
    else await notifyFailure(i18n.t.activeHours.notLoaded, hoursResult.error);
  };

  // Each opening starts fresh: from the next minute until the end of that day, on the server's clock
  $effect(() => {
    if (!isOpen) return;

    // Only opening resets the form, not the config arriving while it's open
    untrack(() => {
      const timezone = config.current?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
      const start = toLocalInput(nextMinute(), timezone);

      visitorName = '';
      visitorType = '';
      visitorSubtype = '';
      ticketType = '';
      validFrom = start;
      validUntil = `${start.slice(0, start.indexOf('T'))}${DAY_END}`;
      usageType = 'one_time';
      groupSize = String(GROUP_MIN);
      isSubmitted = false;
      hasNoVisitorTypes = false;
      hasNoTicketTypes = false;
      // Prices change between openings, so each one reads them again
      void loadCatalog();
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (isBlocked || !(validation.ok && csrfToken) || ticketTypeError) return;

    isPending = true;

    const result = await createTicket(csrfToken, validation.data);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.ticketForm.notCreated, result.error);
      return;
    }

    // A ticket names no one, so its visitor subtype, and group, stand in for the name
    const { group_size: size, readable_serial: serial, visitor_name: name } = result.data;
    const visitor =
      name || (size > 1 ? `${result.data.visitor_type} ×${size}` : result.data.visitor_type);

    toaster.success({
      description: i18n.t.ticketForm.createdFor(serial, visitor),
      title: i18n.t.ticketForm.created,
    });
    onCreated(result.data);
    onClose();
  };
</script>

<FormDialog
  {isOpen}
  {isPending}
  isSubmitDisabled={isBlocked}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.common.create}
  title={i18n.t.ticketForm.title}
>
  {#if isBadge}
    <FloatingInput
      autocomplete="off"
      error={fieldErrors.visitor_name?.[0]}
      id="visitor-name"
      label={i18n.t.ticketForm.visitorName}
      required
      bind:value={visitorName}
    />
  {/if}

  <!-- A badge must be for a visitor type and a ticket for one of a type's subtypes, so with none
       defined there is nothing to pick and the form cannot go on until some are made. Picking
       another type clears the subtype, which belonged to the one before -->
  <FloatingSelect
    disabled={hasNoVisitorTypes}
    error={hasNoVisitorTypes ? undefined : fieldErrors.visitor_type?.[0]}
    id="visitor-type"
    label={i18n.t.ticketForm.visitorType}
    options={visitorTypeOptions}
    bind:value={
      (): string => visitorType,
      (value: string): void => {
    if (value !== visitorType) visitorSubtype = '';
    visitorType = value;
  }
    }
  />
  {#if hasNoVisitorTypes}
    <p class="text-warning-700-300 -mt-3 text-sm" role="alert">
      {isBadge ? i18n.t.ticketForm.noVisitorTypes : i18n.t.ticketForm.noVisitorSubtypes}
    </p>
  {/if}

  {#if !isBadge}
    <FloatingSelect
      disabled={hasNoVisitorTypes || !visitorType}
      error={hasNoVisitorTypes ? undefined : fieldErrors.visitor_subtype?.[0]}
      id="visitor-subtype"
      label={i18n.t.ticketForm.visitorSubtype}
      options={subtypes.map((subtype) => subtype.name)}
      bind:value={visitorSubtype}
    />
  {/if}

  {#if !isBadge}
    <!-- A ticket is priced by its ticket type, so with none defined the form cannot go on -->
    <FloatingSelect
      disabled={hasNoTicketTypes}
      error={hasNoTicketTypes ? undefined : (ticketTypeError ?? fieldErrors.ticket_type?.[0])}
      id="ticket-type"
      label={i18n.t.ticketForm.ticketType}
      options={ticketTypeOptions}
      bind:value={ticketType}
    />
    {#if hasNoTicketTypes}
      <p class="text-warning-700-300 -mt-3 text-sm" role="alert">
        {i18n.t.ticketForm.noTicketTypes}
      </p>
    {/if}
  {/if}

  {#if !isBadge}
    <fieldset class="space-y-2">
      <legend class="label-text">{i18n.t.ticketForm.usage}</legend>
      <!-- Still radios underneath, for arrow keys and the form, but shown as a pair of buttons -->
      <div class="grid grid-cols-2 gap-2">
        {#each USAGE_OPTIONS as { Icon, value: option } (option)}
          <label
            class={[
              'btn has-focus-visible:outline-primary-500 h-12 cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-offset-2',
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

    {#if usageType === 'group'}
      <FloatingInput
        autocomplete="off"
        error={fieldErrors.group_size?.[0]}
        id="group-size"
        inputmode="numeric"
        label={i18n.t.ticketForm.groupSize}
        max={GROUP_MAX}
        min={GROUP_MIN}
        required
        strip={GROUP_CHARS}
        bind:value={groupSize}
      />
    {/if}
  {/if}

  {#if priced}
    <!-- What the API will charge: the type's price less the visitor subtype's discount, once for
         each person the ticket admits -->
    <dl
      aria-live="polite"
      class="rounded-container border-surface-200-800 bg-surface-100-900 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 border px-4 py-3 text-sm tabular-nums"
    >
      <dt class="text-surface-700-300">
        {people === 1 ? i18n.t.ticketForm.price : i18n.t.ticketForm.perPerson}
      </dt>
      <dd class="text-right">{formatMinor(priced.price_minor, priced.currency)}</dd>
      {#if discount > 0}
        <dt class="text-surface-700-300">{i18n.t.ticketForm.discount}</dt>
        <dd class="text-right">−{discount}%</dd>
      {/if}
      {#if people !== 1}
        <dt class="text-surface-700-300">{i18n.t.ticketForm.people}</dt>
        <dd class="text-right">×{people || '—'}</dd>
      {/if}
      <dt class="font-semibold">{i18n.t.ticketForm.total}</dt>
      <dd class="text-right font-semibold">
        {people ? formatMinor(perPerson * people, priced.currency) : '—'}
      </dd>
    </dl>
  {/if}

  <div class="grid gap-4">
    <DateTimeField
      allows={allowsTime}
      error={fieldErrors.valid_from?.[0]}
      id="valid-from"
      label={i18n.t.ticketForm.validFrom}
      timeZone={config.current?.timezone}
      bind:value={validFrom}
    />

    <DateTimeField
      allows={allowsTime}
      error={fieldErrors.valid_until?.[0]}
      id="valid-until"
      label={i18n.t.ticketForm.validUntil}
      min={validFrom}
      timeZone={config.current?.timezone}
      bind:value={validUntil}
    />
  </div>
</FormDialog>
