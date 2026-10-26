import { searchParams } from 'sv-router';

import { type Sort, type SortDirection, type SortValues, toggleSort } from './sort.ts';

type SortParams<Key extends string> = {
  readonly sort: Sort<Key>;
  directionOf: (key: Key) => SortDirection | null;
  sortBy: (key: Key) => void;
};

// Every change replaces the entry, as the pagination does
const OPTIONS = { replace: true };

// The router coerces numeric values, so the raw string is read from a copy
const readParam = (key: string): string | null => searchParams.toURLSearchParams().get(key);

// The column and its direction live in the URL, so a reload or a shared link sorts the same way
const createSortParams = <Row, Key extends string>(
  values: SortValues<Row, Key>,
  fallback: Sort<NoInfer<Key>>
): SortParams<Key> => {
  const isKey = (value: string | null): value is Key =>
    value !== null && Object.hasOwn(values, value);

  const readSort = (): Sort<Key> => {
    const key = readParam('sort');

    if (!isKey(key)) return fallback;

    return { direction: readParam('dir') === 'desc' ? 'desc' : 'asc', key };
  };

  // Defaults leave the URL bare
  const writeSort = (next: Sort<Key>): void => {
    if (next.key === fallback.key && next.direction === fallback.direction) {
      searchParams.delete('sort', undefined, OPTIONS);
      searchParams.delete('dir', undefined, OPTIONS);
      return;
    }

    searchParams.set('sort', next.key, OPTIONS);
    searchParams.set('dir', next.direction, OPTIONS);
  };

  let sort = $state(readSort());

  return {
    directionOf: (key): SortDirection | null => (sort.key === key ? sort.direction : null),
    get sort(): Sort<Key> {
      return sort;
    },
    sortBy: (key): void => {
      sort = toggleSort(sort, key, fallback);
      writeSort(sort);
    },
  };
};

export { createSortParams };
