import { z } from 'zod';

import { i18n } from '%/useLocale.svelte.ts';

const configSchema = z.object({
  server_printing: z.boolean(),
  timezone: z.string(),
});

// HH:MM on the 24-hour clock, as the API sends and takes it
const CLOCK = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

// The hours tickets may be made in, both null when any time is allowed
const activeHoursSchema = z.object({
  end: z.string().regex(CLOCK).nullable(),
  start: z.string().regex(CLOCK).nullable(),
  timezone: z.string(),
});

// The form holds what was picked. Both times empty lifts the limit; otherwise both are needed
const activeHoursInputSchema = z
  .object({
    end: z.string(),
    start: z.string(),
  })
  .superRefine((input, ctx) => {
    if (!(input.start || input.end)) return;

    if (!CLOCK.test(input.start)) {
      ctx.addIssue({ code: 'custom', message: i18n.t.errors.timeRequired, path: ['start'] });
    }
    if (!CLOCK.test(input.end)) {
      ctx.addIssue({ code: 'custom', message: i18n.t.errors.timeRequired, path: ['end'] });
    } else if (input.end === input.start) {
      ctx.addIssue({ code: 'custom', message: i18n.t.errors.sameTime, path: ['end'] });
    }
  });

const MINUTES_IN_HOUR = 60;

const toMinutes = (clock: string): number => {
  const [hours = 0, minutes = 0] = clock.split(':').map(Number);

  return hours * MINUTES_IN_HOUR + minutes;
};

// Whether a whole HH:MM time falls inside the hours, read as the server reads them: from start
// up to end, or past midnight when end comes first
const isWithinHours = (hours: { end: string; start: string }, clock: string): boolean => {
  const moment = toMinutes(clock);
  const start = toMinutes(hours.start);
  const end = toMinutes(hours.end);

  return start < end ? start <= moment && moment < end : moment >= start || moment < end;
};

// Whether a window may close at a whole HH:MM time: inside the hours, or exactly at their end
const isEndWithinHours = (hours: { end: string; start: string }, clock: string): boolean =>
  isWithinHours(hours, clock) || clock === hours.end;

const DAY_MS = 86_400_000;

// The day, YYYY-MM-DD, moved by whole days
const shiftDay = (day: string, days: number): string =>
  new Date(Date.parse(`${day}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);

// The window to start a ticket with when hours are set: the hours themselves, on the day they are
// in force at `local` (a YYYY-MM-DDTHH:MM wall-clock time). Hours that run past midnight belong to
// the day they began, so just after midnight that is yesterday; the end then falls on the next day
const hoursWindow = (
  hours: { end: string; start: string },
  local: string
): { end: string; start: string } => {
  const [day = '', clock = ''] = local.split('T');
  const wraps = toMinutes(hours.end) <= toMinutes(hours.start);
  const first = wraps && toMinutes(clock) < toMinutes(hours.end) ? shiftDay(day, -1) : day;

  return {
    end: `${wraps ? shiftDay(first, 1) : first}T${hours.end}`,
    start: `${first}T${hours.start}`,
  };
};

const countSchema = z.object({ count: z.number().int().nonnegative() });

const countsSchema = z.object({
  expired: z.number().int().nonnegative(),
  issued: z.number().int().nonnegative(),
  passed: z.number().int().nonnegative(),
  passes: z.number().int().nonnegative(),
  prints: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
});

const visitorStatsSchema = countsSchema.extend({
  ticket_types: z.record(z.string(), countsSchema),
});

const statsSchema = countsSchema.extend({
  ticket_types: z.record(z.string(), countsSchema),
  visitor_types: z.record(z.string(), visitorStatsSchema),
});

type ActiveHours = z.infer<typeof activeHoursSchema>;
type ActiveHoursInput = z.infer<typeof activeHoursInputSchema>;
type Config = z.infer<typeof configSchema>;
type Counts = z.infer<typeof countsSchema>;
type Stats = z.infer<typeof statsSchema>;

// The figures the stats page shows, in its order; each is labelled in the showing language
const METRICS = ['total', 'issued', 'passed', 'expired'] satisfies (keyof Counts)[];
// The summed counters, shown last with their own meanings
const TALLIES = ['prints', 'passes'] satisfies (keyof Counts)[];

export type { ActiveHours, ActiveHoursInput, Config, Counts, Stats };
export {
  METRICS,
  TALLIES,
  activeHoursInputSchema,
  activeHoursSchema,
  configSchema,
  countSchema,
  hoursWindow,
  isEndWithinHours,
  isWithinHours,
  statsSchema,
};
