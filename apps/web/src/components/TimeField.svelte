<script lang="ts">
  import Clock from '@lucide/svelte/icons/clock';
  import { Popover } from '@skeletonlabs/skeleton-svelte';
  import { untrack } from 'svelte';

  import { i18n } from '%/useLocale.svelte.ts';

  type TimeFieldProps = {
    label: string;
    // 24-hour HH:MM; empty until a whole time is typed or picked
    value: string;
    describedBy?: string;
    isInvalid?: boolean;
    // Whether a whole HH:MM time may be picked; the picker greys out the times that may not
    allows?: (time: string) => boolean;
  };

  let {
    label,
    value = $bindable(''),
    describedBy,
    isInvalid = false,
    allows = (): boolean => true,
  }: TimeFieldProps = $props();

  const ICON_SIZE = 16;
  const HOURS_IN_DAY = 24;
  const MINUTES_IN_HOUR = 60;
  // Typed times are 24-hour, with or without the colon: 9:30, 09:30 or 0930
  const MAX_LENGTH = 'HH:MM'.length;
  const TYPED_TIME = /^(?<hours>\d{1,2}):?(?<minutes>\d{2})$/;

  const pad = (part: number): string => String(part).padStart(2, '0');

  const HOURS = Array.from({ length: HOURS_IN_DAY }, (_, hour) => pad(hour));
  const MINUTES = Array.from({ length: MINUTES_IN_HOUR }, (_, minute) => pad(minute));

  const parse = (typed: string): string => {
    const { hours, minutes } = TYPED_TIME.exec(typed.trim())?.groups ?? {};

    if (!(hours && minutes)) return '';
    if (Number(hours) >= HOURS_IN_DAY || Number(minutes) >= MINUTES_IN_HOUR) return '';

    return `${pad(Number(hours))}:${minutes}`;
  };

  let text = $state('');
  let isOpen = $state(false);

  // Takes in values set from outside (a pick, the form resetting), but not the echo of our typing
  $effect.pre(() => {
    const next = value;

    untrack(() => {
      if (next !== parse(text)) text = next;
    });
  });

  const [selectedHour = '', selectedMinute = ''] = $derived(value ? value.split(':') : []);

  // An hour is off when none of its minutes may be picked
  const isHourOff = (hour: string): boolean =>
    MINUTES.every((minute) => !allows(`${hour}:${minute}`));
  // Minutes belong to the hour picked, or to the first hour on when none is picked yet
  const firstHourOn = $derived(HOURS.find((hour) => !isHourOff(hour)) ?? '00');
  const isMinuteOff = (minute: string): boolean =>
    !allows(`${selectedHour || firstHourOn}:${minute}`);

  // Keeps the minute picked when this hour allows it, else takes the first minute it allows
  const pickHour = (hour: string): void => {
    const minute =
      selectedMinute && allows(`${hour}:${selectedMinute}`)
        ? selectedMinute
        : (MINUTES.find((option) => allows(`${hour}:${option}`)) ?? '00');

    value = `${hour}:${minute}`;
  };

  // The minute finishes a pick, so it closes the list
  const pickMinute = (minute: string): void => {
    value = `${selectedHour || firstHourOn}:${minute}`;
    isOpen = false;
  };

  // Attached to each column: opens with the picked hour and minute in the middle of theirs. Only the
  // opening is tracked, so a pick inside the open list leaves the scroll where it is
  const centerSelected = (column: HTMLDivElement): void => {
    if (!isOpen) return;

    requestAnimationFrame(() => {
      const selected = column.querySelector<HTMLElement>('[aria-pressed="true"]');

      if (!selected) return;

      column.scrollTop = selected.offsetTop - (column.clientHeight - selected.offsetHeight) / 2;
    });
  };
</script>

{#snippet column(
  legend: string,
  options: string[],
  selected: string,
  onPick: (option: string) => void,
  isOff: (option: string) => boolean
)}
  <fieldset class="flex flex-col items-center gap-1">
    <legend class="text-surface-600-400 mb-1 w-full text-center text-xs font-medium">
      {legend}
    </legend>
    <div
      class="relative flex h-56 w-14 [scrollbar-width:thin] flex-col gap-0.5 overflow-y-auto pr-1"
      {@attach centerSelected}
    >
      {#each options as option (option)}
        <button
          aria-pressed={option === selected}
          class={[
            'rounded-base shrink-0 py-1.5 text-sm tabular-nums disabled:opacity-35',
            option === selected ? 'preset-filled-primary-500' : 'enabled:hover:preset-tint-primary',
          ]}
          disabled={isOff(option)}
          onclick={(): void => {
            onPick(option);
          }}
          type="button"
        >
          {option}
        </button>
      {/each}
    </div>
  </fieldset>
{/snippet}

<Popover
  onOpenChange={({ open }): void => {
    isOpen = open;
  }}
  open={isOpen}
  positioning={{ placement: 'bottom-end' }}
>
  <div class="relative w-28 shrink-0">
    <input
      aria-describedby={describedBy}
      aria-invalid={isInvalid ? 'true' : undefined}
      aria-label={label}
      autocomplete="off"
      class="input aria-invalid:ring-error-500 pr-10 tabular-nums"
      inputmode="numeric"
      maxlength={MAX_LENGTH}
      onblur={(): void => {
        // Tidies 930 or 9:30 into 09:30 once the field is left
        if (value) text = value;
      }}
      oninput={(event): void => {
        text = event.currentTarget.value;
        value = parse(text);
      }}
      placeholder={i18n.t.dateField.timePlaceholder}
      required
      type="text"
      value={text}
    />
    <Popover.Trigger
      aria-label={i18n.t.dateField.openTimePicker}
      class="btn-icon text-surface-600-400 hover:preset-tint-primary absolute top-1/2 right-1 size-8 -translate-y-1/2 bg-transparent"
    >
      <Clock aria-hidden="true" size={ICON_SIZE} />
    </Popover.Trigger>
  </div>

  <!-- Not portalled: inside the dialog, so its focus trap and Escape handling keep working. The
       z-index sits on the content: the positioner copies it into an inline style of its own -->
  <Popover.Positioner>
    <Popover.Content
      class="card border-surface-200-800 bg-surface-50-950 z-30 flex gap-2 border p-2 shadow-xl"
    >
      {@render column(i18n.t.dateField.hours, HOURS, selectedHour, pickHour, isHourOff)}
      {@render column(i18n.t.dateField.minutes, MINUTES, selectedMinute, pickMinute, isMinuteOff)}
    </Popover.Content>
  </Popover.Positioner>
</Popover>
