<script lang="ts">
  import CalendarDays from '@lucide/svelte/icons/calendar-days';
  import { DatePicker, type DateValue, parseDate } from '@skeletonlabs/skeleton-svelte';
  import { untrack } from 'svelte';

  import CalendarContent from '@/components/CalendarContent.svelte';
  import FieldError from '@/components/FieldError.svelte';
  import TimeField from '@/components/TimeField.svelte';
  import { i18n } from '%/useLocale.svelte.ts';

  type DateTimeFieldProps = {
    id: string;
    label: string;
    // A <input type="datetime-local"> style value, YYYY-MM-DDTHH:MM; empty until both halves are set
    value: string;
    // Same format; only its date bounds the calendar
    min?: string;
    // Marks today in the calendar on this zone's clock
    timeZone?: string;
    error?: string;
  };

  let { id, label, value = $bindable(''), min, timeZone, error }: DateTimeFieldProps = $props();

  const ICON_SIZE = 16;
  const MONDAY = 1;
  // Typed dates read day first, like the tickets table: 21.10.2026, 21/10/2026 or 21-10-2026
  const TYPED_DATE = /^(?<day>\d{1,2})[./-](?<month>\d{1,2})[./-](?<year>\d{4})$/;

  const errorId = $derived(`${id}-error`);

  let date = $state('');
  let time = $state('');

  const compose = (datePart: string, timePart: string): string =>
    datePart && timePart ? `${datePart}T${timePart}` : '';

  // Takes in values set from outside (the form resetting), but not the echo of our own commit
  $effect.pre(() => {
    const next = value;

    untrack(() => {
      if (next === compose(date, time)) return;

      date = next.slice(0, next.indexOf('T'));
      time = next.slice(next.indexOf('T') + 1);
    });
  });

  const commit = (): void => {
    value = compose(date, time);
  };

  const toDateValue = (iso: string | undefined): DateValue | undefined => {
    if (!iso) return undefined;

    try {
      return parseDate(iso.slice(0, 10));
    } catch {
      return undefined;
    }
  };

  const selected = $derived(toDateValue(date));
  const minDate = $derived(toDateValue(min));

  const pad = (part: number | string): string => String(part).padStart(2, '0');

  const format = (day: DateValue): string => `${pad(day.day)}.${pad(day.month)}.${day.year}`;

  const parse = (text: string): DateValue | undefined => {
    const { day, month, year } = TYPED_DATE.exec(text.trim())?.groups ?? {};

    return day && month && year ? toDateValue(`${year}-${pad(month)}-${pad(day)}`) : undefined;
  };
</script>

<DatePicker
  closeOnSelect
  {format}
  locale={i18n.code}
  min={minDate}
  onValueChange={({ value: [picked] }): void => {
    date = picked?.toString() ?? '';
    commit();
  }}
  {parse}
  placeholder={i18n.t.dateField.placeholder}
  startOfWeek={MONDAY}
  {timeZone}
  value={selected ? [selected] : []}
>
  <DatePicker.Label>{label}</DatePicker.Label>
  <div class="flex gap-2">
    <DatePicker.Control class="flex-1">
      <DatePicker.Input
        aria-describedby={error ? errorId : undefined}
        aria-invalid={error ? 'true' : undefined}
        class="aria-invalid:ring-error-500 pr-11"
        placeholder={i18n.t.dateField.placeholder}
      />
      <DatePicker.Trigger
        aria-label={i18n.t.dateField.openCalendar}
        class="text-surface-600-400 hover:preset-tint-primary top-1/2 right-1 size-8 -translate-y-1/2 bg-transparent"
      >
        <CalendarDays aria-hidden="true" size={ICON_SIZE} />
      </DatePicker.Trigger>
    </DatePicker.Control>
    <TimeField
      describedBy={error ? errorId : undefined}
      isInvalid={Boolean(error)}
      label={`${label}, ${i18n.t.dateField.time}`}
      bind:value={
        (): string => time,
        (next: string): void => {
    time = next;
    commit();
  }
      }
    />
  </div>
  <FieldError {error} id={errorId} />

  <!-- Not portalled: inside the dialog, so its focus trap and Escape handling keep working -->
  <CalendarContent />
</DatePicker>
