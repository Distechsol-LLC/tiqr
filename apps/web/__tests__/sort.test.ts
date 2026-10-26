import { describe, expect, test as it } from 'bun:test';

import { sortRows, toggleSort } from '%/sort.ts';

type Row = { name: string; uses: number };

const BUSY = 3;
const IDLE = 1;

const rows: Row[] = [
  { name: 'ticket 10', uses: BUSY },
  { name: 'ticket 2', uses: IDLE },
  { name: 'Ada', uses: BUSY },
];

const values = {
  name: (row: Row) => row.name,
  uses: (row: Row) => row.uses,
} as const;

describe('toggleSort', () => {
  it('cycles a column through ascending, descending and then back to the default', () => {
    const fallback = { direction: 'asc', key: 'uses' } as const;
    const first = toggleSort(fallback, 'name', fallback);
    const second = toggleSort(first, 'name', fallback);
    const third = toggleSort(second, 'name', fallback);

    expect(first).toEqual({ direction: 'asc', key: 'name' });
    expect(second).toEqual({ direction: 'desc', key: 'name' });
    expect(third).toEqual(fallback);
  });

  it('starts over ascending when the default is already descending', () => {
    const fallback = { direction: 'desc', key: 'name' } as const;
    const first = toggleSort(fallback, 'name', fallback);
    const second = toggleSort(first, 'name', fallback);

    expect(first).toEqual({ direction: 'asc', key: 'name' });
    expect(second).toEqual(fallback);
    expect(toggleSort(second, 'name', fallback)).toEqual({ direction: 'asc', key: 'name' });
  });

  it('starts a different column ascending, whatever the previous direction was', () => {
    const fallback = { direction: 'asc', key: 'name' } as const;

    expect(toggleSort({ direction: 'desc', key: 'name' }, 'uses', fallback)).toEqual({
      direction: 'asc',
      key: 'uses',
    });
  });
});

describe('sortRows', () => {
  it('sorts numbers by value in both directions', () => {
    const asc = sortRows(rows, { direction: 'asc', key: 'uses' }, values).map((row) => row.uses);
    const desc = sortRows(rows, { direction: 'desc', key: 'uses' }, values).map((row) => row.uses);

    expect(asc).toEqual([IDLE, BUSY, BUSY]);
    expect(desc).toEqual([BUSY, BUSY, IDLE]);
  });

  it('sorts text naturally, so "ticket 2" comes before "ticket 10"', () => {
    const names = sortRows(rows, { direction: 'asc', key: 'name' }, values).map((row) => row.name);

    expect(names).toEqual(['Ada', 'ticket 2', 'ticket 10']);
  });

  it('keeps tied rows in their incoming order', () => {
    const sorted = sortRows(rows, { direction: 'desc', key: 'uses' }, values);

    expect(sorted.filter((row) => row.uses === BUSY).map((row) => row.name)).toEqual([
      'ticket 10',
      'Ada',
    ]);
  });

  it('leaves the input array untouched', () => {
    const before = rows.map((row) => row.name);

    sortRows(rows, { direction: 'asc', key: 'name' }, values);

    expect(rows.map((row) => row.name)).toEqual(before);
  });
});
