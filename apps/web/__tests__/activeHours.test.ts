import { afterEach, beforeEach, describe, expect, test as it } from 'bun:test';

import { i18n } from '%/useLocale.svelte.ts';
import { activeHoursInputSchema, activeHoursSchema, isWithinHours } from '$/operations.ts';

describe('active hours', () => {
  beforeEach(() => {
    i18n.set('en');
  });

  afterEach(() => {
    i18n.set('en');
  });

  it('reads the hours the API sends, with both ends null when any time is allowed', () => {
    expect(
      activeHoursSchema.parse({ end: '17:00', start: '09:00', timezone: 'Asia/Baku' })
    ).toEqual({ end: '17:00', start: '09:00', timezone: 'Asia/Baku' });
    expect(
      activeHoursSchema.parse({ end: null, start: null, timezone: 'Asia/Baku' }).start
    ).toBeNull();
    expect(() =>
      activeHoursSchema.parse({ end: '5pm', start: '09:00', timezone: 'Asia/Baku' })
    ).toThrow();
  });

  it('lifts the limit when both times are empty', () => {
    expect(activeHoursInputSchema.safeParse({ end: '', start: '' }).success).toBe(true);
  });

  it('needs both times when either is filled, and they must differ', () => {
    const missingEnd = activeHoursInputSchema.safeParse({ end: '', start: '09:00' });
    expect(missingEnd.error?.issues.map((issue) => issue.path)).toEqual([['end']]);
    expect(missingEnd.error?.issues[0]?.message).toBe(i18n.t.errors.timeRequired);

    const missingStart = activeHoursInputSchema.safeParse({ end: '17:00', start: '' });
    expect(missingStart.error?.issues.map((issue) => issue.path)).toEqual([['start']]);

    const same = activeHoursInputSchema.safeParse({ end: '09:00', start: '09:00' });
    expect(same.error?.issues[0]?.message).toBe(i18n.t.errors.sameTime);

    expect(activeHoursInputSchema.safeParse({ end: '17:00', start: '09:00' }).success).toBe(true);
  });

  it('rejects times that are not 24-hour HH:MM', () => {
    for (const start of ['9:00', '24:00', '12:60']) {
      expect(activeHoursInputSchema.safeParse({ end: '17:00', start }).success).toBe(false);
    }
  });
});

describe('isWithinHours', () => {
  it('admits the start and refuses the end, as the server does', () => {
    const hours = { end: '17:00', start: '09:00' };

    expect(isWithinHours(hours, '09:00')).toBe(true);
    expect(isWithinHours(hours, '16:59')).toBe(true);
    expect(isWithinHours(hours, '08:59')).toBe(false);
    expect(isWithinHours(hours, '17:00')).toBe(false);
  });

  it('runs past midnight when the end comes first', () => {
    const night = { end: '06:00', start: '22:00' };

    expect(isWithinHours(night, '23:30')).toBe(true);
    expect(isWithinHours(night, '05:59')).toBe(true);
    expect(isWithinHours(night, '06:00')).toBe(false);
    expect(isWithinHours(night, '12:00')).toBe(false);
  });
});
