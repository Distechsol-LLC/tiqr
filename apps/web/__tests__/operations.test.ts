import { describe, expect, test as it } from 'bun:test';

import { configSchema, countSchema, statsSchema } from '$/operations.ts';

const counts = {
  expired: 2,
  issued: 4,
  passed: 2,
  total: 8,
};

const stats = {
  ...counts,
  ticket_types: {
    '': { ...counts, issued: 1, total: 1 },
    Day: counts,
    Week: { ...counts, issued: 3, total: 5 },
  },
  visitor_types: {
    Guest: {
      ...counts,
      issued: 3,
      ticket_types: {
        '': { ...counts, issued: 1, total: 1 },
        Week: { ...counts, issued: 2, total: 4 },
      },
      total: 5,
    },
    Staff: { ...counts, ticket_types: { Day: counts } },
  },
};

describe('operations schemas', () => {
  it('parses the server configuration', () => {
    expect(configSchema.parse({ server_printing: false, timezone: 'Asia/Baku' })).toEqual({
      server_printing: false,
      timezone: 'Asia/Baku',
    });
  });

  it('rejects a configuration missing the timezone', () => {
    expect(configSchema.safeParse({ server_printing: true }).success).toBe(false);
  });

  it('parses the overview statistics as they come from the server', () => {
    expect(statsSchema.parse(stats)).toEqual(stats);
  });

  it('rejects statistics with a negative or fractional count', () => {
    expect(statsSchema.safeParse({ ...stats, issued: -1 }).success).toBe(false);
    expect(statsSchema.safeParse({ ...stats, issued: 1.5 }).success).toBe(false);
  });

  it('rejects statistics missing a field', () => {
    const { expired: _expired, ...withoutExpired } = stats;

    expect(statsSchema.safeParse(withoutExpired).success).toBe(false);
  });

  it('parses a bare count, as sync and cleanup return', () => {
    expect(countSchema.parse({ count: 0 })).toEqual({ count: 0 });
    expect(countSchema.safeParse({ count: -2 }).success).toBe(false);
  });
});
