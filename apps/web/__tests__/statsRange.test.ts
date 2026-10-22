import { describe, expect, test as it } from 'bun:test';

import { moveAnchor, shiftAnchor, spanOf } from '%/statsRange.ts';

describe('statsRange', () => {
  it('covers the whole day, month or year a day falls in', () => {
    expect(spanOf('day', '2026-09-17')).toEqual({ since: '2026-09-17', until: '2026-09-17' });
    expect(spanOf('month', '2026-09-17')).toEqual({ since: '2026-09-01', until: '2026-09-30' });
    expect(spanOf('month', '2028-02-10')).toEqual({ since: '2028-02-01', until: '2028-02-29' });
    expect(spanOf('year', '2026-09-17')).toEqual({ since: '2026-01-01', until: '2026-12-31' });
  });

  it('steps by days across months and years', () => {
    expect(shiftAnchor('day', '2026-12-31', 1)).toBe('2027-01-01');
    expect(shiftAnchor('day', '2026-03-01', -1)).toBe('2026-02-28');
  });

  it('steps by months and years, keeping the day where the month has it', () => {
    expect(shiftAnchor('month', '2026-03-31', -1)).toBe('2026-02-28');
    expect(shiftAnchor('month', '2026-12-15', 1)).toBe('2027-01-15');
    expect(shiftAnchor('month', '2026-01-15', -1)).toBe('2025-12-15');
    expect(shiftAnchor('year', '2028-02-29', 1)).toBe('2029-02-28');
    expect(shiftAnchor('year', '2026-09-17', -1)).toBe('2025-09-17');
  });

  it('moves to a picked month or year, keeping the rest of the day showing', () => {
    expect(moveAnchor('year', '2026-03-14', '2025-01-01')).toBe('2025-03-14');
    expect(moveAnchor('month', '2026-03-14', '2025-11-01')).toBe('2025-11-14');
    expect(moveAnchor('month', '2026-03-31', '2026-02-01')).toBe('2026-02-28');
    expect(moveAnchor('day', '2026-03-14', '2026-03-02')).toBe('2026-03-02');
  });
});
