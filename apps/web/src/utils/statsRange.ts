// Calendar days as YYYY-MM-DD, the server's `since` and `until`; computed in UTC so the
// browser's own zone never shifts a day
type Span = 'day' | 'month' | 'year';

type DateRange = { since: string; until: string };

const MONTHS = 12;

const pad = (part: number): string => String(part).padStart(2, '0');

const toIso = (date: Date): string =>
  `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;

const parts = (iso: string): [number, number, number] => {
  const [year = 0, month = 1, day = 1] = iso.split('-').map(Number);

  return [year, month - 1, day];
};

// Day 0 of the next month is the last of this one
const lastDayOf = (year: number, month: number): number =>
  new Date(Date.UTC(year, month + 1, 0)).getUTCDate();

// The whole day, month or year that `anchor` falls in
const spanOf = (span: Span, anchor: string): DateRange => {
  const [year, month] = parts(anchor);

  switch (span) {
    case 'day':
      return { since: anchor, until: anchor };
    case 'month':
      return {
        since: `${year}-${pad(month + 1)}-01`,
        until: `${year}-${pad(month + 1)}-${pad(lastDayOf(year, month))}`,
      };
    case 'year':
      return { since: `${year}-01-01`, until: `${year}-12-31` };
    default:
      return span satisfies never;
  }
};

// Moves by whole spans, keeping the day where the month allows: 31 March back one is 28/29 Feb
const shiftAnchor = (span: Span, anchor: string, step: number): string => {
  const [year, month, day] = parts(anchor);

  if (span === 'day') return toIso(new Date(Date.UTC(year, month, day + step)));

  const target = new Date(Date.UTC(year + (span === 'year' ? step : 0), month, 1));

  if (span === 'month') target.setUTCMonth(month + step);

  const last = lastDayOf(target.getUTCFullYear(), target.getUTCMonth());

  return toIso(
    new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), Math.min(day, last)))
  );
};

// Moves to the month or year of `picked` (the calendar gives its first day), keeping the rest of
// `anchor`, so picking 2025 from 14 March 2026 lands on 14 March 2025
const moveAnchor = (span: Span, anchor: string, picked: string): string => {
  const [year, month] = parts(anchor);
  const [pickedYear, pickedMonth] = parts(picked);

  switch (span) {
    case 'day':
      return picked;
    case 'month':
      return shiftAnchor('month', anchor, (pickedYear - year) * MONTHS + pickedMonth - month);
    case 'year':
      return shiftAnchor('year', anchor, pickedYear - year);
    default:
      return span satisfies never;
  }
};

export type { DateRange, Span };
export { moveAnchor, shiftAnchor, spanOf };
