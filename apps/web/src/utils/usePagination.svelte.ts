import { searchParams } from 'sv-router';

import { DEFAULT_SIZE } from '$/pagination.ts';
import { parsePage, parseSize } from './pagination.ts';

type PaginationController = {
  readonly page: number;
  readonly size: number;
  goTo: (page: number) => void;
  resize: (size: number) => void;
};

// Every change replaces the entry: one move is two params, and each write would push its own
const OPTIONS = { replace: true };

// The router coerces numeric values, so the raw string is read from a copy
const readParam = (key: string): string | null => searchParams.toURLSearchParams().get(key);

// Defaults leave the URL bare
const writeParam = (key: string, value: number, fallback: number): void => {
  if (value === fallback) searchParams.delete(key, undefined, OPTIONS);
  else searchParams.set(key, value, OPTIONS);
};

// The page and size live in the URL, so a reload or a shared link shows the same rows
const createPagination = (): PaginationController => {
  let page = $state(parsePage(readParam('page')));
  let size = $state(parseSize(readParam('size')));

  return {
    goTo: (next): void => {
      page = next;
      writeParam('page', page, 1);
    },
    get page(): number {
      return page;
    },
    resize: (next): void => {
      size = next;
      // The rows the old page held are spread differently now
      page = 1;
      writeParam('page', page, 1);
      writeParam('size', size, DEFAULT_SIZE);
    },
    get size(): number {
      return size;
    },
  };
};

export { createPagination };
