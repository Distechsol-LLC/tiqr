export type SortDirection = 'asc' | 'desc';

export type Sort<Key extends string> = {
  key: Key;
  direction: SortDirection;
};

// Each key maps to the value its column is ordered by
export type SortValues<Row, Key extends string> = Record<Key, (row: Row) => number | string>;

// A column's first press sorts ascending, the second descending, the third restores the default.
// A default that is already descending is the second press, so the third starts over ascending.
export const toggleSort = <Key extends string>(
  current: Sort<Key>,
  key: Key,
  fallback: Sort<Key>
): Sort<Key> => {
  if (current.key !== key) return { direction: 'asc', key };
  if (current.direction === 'asc') return { direction: 'desc', key };
  if (fallback.key === key && fallback.direction === 'desc') return { direction: 'asc', key };

  return fallback;
};

// Stable, so rows that tie keep the order they came in
export const sortRows = <Row, Key extends string>(
  rows: Row[],
  sort: Sort<Key>,
  values: SortValues<Row, Key>
): Row[] => {
  const read = values[sort.key];
  const sign = sort.direction === 'asc' ? 1 : -1;

  return rows.toSorted((a, b) => {
    const left = read(a);
    const right = read(b);

    return (
      sign *
      (typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right), undefined, { numeric: true }))
    );
  });
};
