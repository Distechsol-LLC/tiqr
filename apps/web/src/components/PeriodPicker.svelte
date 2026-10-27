<script lang="ts">
  import CalendarDays from '@lucide/svelte/icons/calendar-days';
  import { DatePicker, type DateValue, parseDate } from '@skeletonlabs/skeleton-svelte';

  import CalendarContent from '@/components/CalendarContent.svelte';
  import type { Span } from '%/statsRange.ts';
  import { i18n } from '%/useLocale.svelte.ts';

  type PeriodPickerProps = {
    label: string;
    // A day, month or year is picked through any day in it; a range takes its first and last
    mode: Span | 'range';
    // YYYY-MM-DD days: one, or a range's two
    value: string[];
    // The last pickable day, YYYY-MM-DD
    max?: string;
    // Marks today in the calendar on this zone's clock
    timeZone?: string;
  };

  let { label, mode, value = $bindable([]), max, timeZone }: PeriodPickerProps = $props();

  const ICON_SIZE = 16;
  const MONDAY = 1;

  const toDateValue = (iso: string | undefined): DateValue | undefined => {
    if (!iso) return undefined;

    try {
      return parseDate(iso);
    } catch {
      return undefined;
    }
  };

  const toDateValues = (days: string[]): DateValue[] =>
    days.map(toDateValue).filter((day): day is DateValue => day !== undefined);

  // A range's first click is held here until its second, so half a range never loads
  let picked = $state<DateValue[]>([]);

  $effect.pre(() => {
    picked = toDateValues(value);
  });

  const commit = (days: DateValue[]): void => {
    picked = days;

    if (days.length === (mode === 'range' ? 2 : 1)) value = days.map((day) => day.toString());
  };

  const minView = $derived(mode === 'month' || mode === 'year' ? mode : 'day');

  const formatDay = (iso: string): string => {
    const [year, month, day] = iso.split('-');

    return `${day}.${month}.${year}`;
  };

  const formatMonth = (iso: string): string => {
    const [year = '', month = ''] = iso.split('-');

    const text = new Intl.DateTimeFormat(i18n.code, {
      month: 'long',
      timeZone: 'UTC',
      year: 'numeric',
    }).format(new Date(Date.UTC(Number(year), Number(month) - 1)));

    // Russian and Azerbaijani write months in lower case; only the label's start goes up
    return text.charAt(0).toLocaleUpperCase(i18n.code) + text.slice(1);
  };

  // Shown on the button: the day as the tickets table writes it, months in the showing language
  const text = $derived.by(() => {
    const [first = '', last = first] = value;

    switch (mode) {
      case 'day':
        return formatDay(first);
      case 'month':
        return formatMonth(first);
      case 'year':
        return first.split('-')[0] ?? '';
      case 'range':
        return first === last ? formatDay(first) : `${formatDay(first)} – ${formatDay(last)}`;
      default:
        return mode satisfies never;
    }
  });
</script>

<!-- Keyed, so a new mode starts the calendar on its own view -->
{#key mode}
  <DatePicker
    closeOnSelect
    defaultView={minView}
    locale={i18n.code}
    max={toDateValue(max)}
    {minView}
    onOpenChange={({ open }): void => {
      // A range left half-picked goes back to the one showing
      if (!open) picked = toDateValues(value);
    }}
    onValueChange={({ value: days }): void => commit(days)}
    selectionMode={mode === 'range' ? 'range' : 'single'}
    startOfWeek={MONDAY}
    {timeZone}
    value={picked}
  >
    <DatePicker.Label class="sr-only">{label}</DatePicker.Label>
    <!-- Skeleton places the trigger as an icon over an input; here it's the whole control -->
    <DatePicker.Control>
      <!-- Named with its value: Zag's own label is a fixed "Open calendar" -->
      <DatePicker.Trigger
        aria-label="{label}: {text}"
        class="btn preset-filled-surface-50-950 border-surface-200-800 hover:border-primary-500 static h-9 w-72 translate-none justify-start border tabular-nums"
        title={label}
      >
        <CalendarDays aria-hidden="true" class="shrink-0" size={ICON_SIZE} />
        <span>{text}</span>
      </DatePicker.Trigger>
    </DatePicker.Control>

    <CalendarContent />
  </DatePicker>
{/key}
