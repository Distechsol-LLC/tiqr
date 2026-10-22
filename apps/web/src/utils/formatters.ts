const MINUTE_MS = 60_000;

const formatters = new Map<string, Intl.DateTimeFormat>();

// The badge's own format, dd.mm.yy · HH:MM, in the zone the server shows tickets in
const formatDatetime = (iso: string, timeZone: string): string => {
  let formatter = formatters.get(timeZone);

  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      day: '2-digit',
      hour: '2-digit',
      hourCycle: 'h23',
      minute: '2-digit',
      month: '2-digit',
      timeZone,
      year: '2-digit',
    });
    formatters.set(timeZone, formatter);
  }

  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(iso)).map(({ type, value }) => [type, value])
  );

  return `${parts.day}.${parts.month}.${parts.year} · ${parts.hour}:${parts.minute}`;
};

// A <input type="datetime-local"> value for a moment, read on the server's wall clock
const toLocalInput = (date: Date, timeZone: string): string => {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      day: '2-digit',
      hour: '2-digit',
      hourCycle: 'h23',
      minute: '2-digit',
      month: '2-digit',
      timeZone,
      year: 'numeric',
    })
      .formatToParts(date)
      .map(({ type, value }) => [type, value])
  );

  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
};

// Starts the next whole minute, so the window isn't already behind the clock when it arrives
const nextMinute = (now = new Date()): Date =>
  new Date(Math.ceil((now.getTime() + 1) / MINUTE_MS) * MINUTE_MS);

export { formatDatetime, nextMinute, toLocalInput };
