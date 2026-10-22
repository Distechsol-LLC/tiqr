import { describe, expect, test as it } from 'bun:test';

import { formatDatetime, nextMinute, toLocalInput } from '%/formatters.ts';

describe('formatters', () => {
  it('formats in the ticket zone, as the badge does', () => {
    expect(formatDatetime('2030-06-01T09:05:00+04:00', 'Asia/Baku')).toBe('01.06.30 · 09:05');
    expect(formatDatetime('2030-06-01T09:05:00+04:00', 'UTC')).toBe('01.06.30 · 05:05');
  });

  it('writes datetime-local values on the server clock', () => {
    expect(toLocalInput(new Date('2030-06-01T20:30:00Z'), 'Asia/Baku')).toBe('2030-06-02T00:30');
  });

  it('rounds up to the next whole minute', () => {
    expect(nextMinute(new Date('2030-06-01T09:05:30Z')).toISOString()).toBe(
      '2030-06-01T09:06:00.000Z'
    );
    expect(nextMinute(new Date('2030-06-01T09:05:00Z')).toISOString()).toBe(
      '2030-06-01T09:06:00.000Z'
    );
  });
});
