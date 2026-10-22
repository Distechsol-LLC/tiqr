export type SortDirection = 'asc' | 'desc';

export type Sort<Key extends string> = {
  key: Key;
  direction: SortDirection;
};

// Each key maps to the value its column is ordered by
export type SortValues<Row, Key extends string> = Record<Key, (row: Row) => number | string>;

// A column's first press sorts ascending, the second descending, the third restores the default
export const toggleSort = <Key extends string>(
  current: Sort<Key> | null,
  key: Key
): Sort<Key> | null => {
  if (current?.key !== key) return { direction: 'asc', key };

  return current.direction === 'asc' ? { direction: 'desc', key } : null;
};

// Stable, so rows that tie keep the order they came in
export const sortRows = <Row, Key extends string>(
  rows: Row[],
  sort: Sort<Key> | null,
  values: SortValues<Row, Key>
): Row[] => {
  if (!sort) return rows;

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
