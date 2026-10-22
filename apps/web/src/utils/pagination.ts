import { DEFAULT_SIZE, PAGE_SIZES } from '$/pagination.ts';

// Anything that isn't a whole page number from 1 reads as the first page
export const parsePage = (raw: string | null): number => {
  const page = Number(raw);

  return Number.isInteger(page) && page >= 1 ? page : 1;
};

// Only the offered sizes count, so a hand-edited URL can't ask for another
export const parseSize = (raw: string | null): number =>
  PAGE_SIZES.find((size) => String(size) === raw) ?? DEFAULT_SIZE;

// An empty list still has its one page
export const pageCount = (total: number, size: number): number =>
  Math.max(1, Math.ceil(total / size));

// The 1-based positions of the first and last item on a page, 0 and 0 when there are none
export const itemRange = (page: number, size: number, total: number): [number, number] =>
  total === 0 ? [0, 0] : [(page - 1) * size + 1, Math.min(page * size, total)];
