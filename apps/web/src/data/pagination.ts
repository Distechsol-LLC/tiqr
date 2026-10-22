import { z } from 'zod';

// What the footer offers; the API accepts any size up to MAX_SIZE
// biome-ignore lint/style/noMagicNumbers: the sizes are the point
const PAGE_SIZES = [10, 20, 50, 100] as const;
const DEFAULT_SIZE = 20;
// Same bound as _MAX_SIZE in apps/api/src/tiqr/api/endpoints.py
const MAX_SIZE = 100;

const pageSchema = <Item extends z.ZodType>(
  item: Item
): z.ZodObject<{
  items: z.ZodArray<Item>;
  page: z.ZodNumber;
  size: z.ZodNumber;
  total: z.ZodNumber;
}> =>
  z.object({
    items: z.array(item),
    page: z.number().int().positive(),
    size: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  });

type PageRequest = {
  page: number;
  size: number;
};

type Page<Item> = PageRequest & {
  items: Item[];
  total: number;
};

export type { Page, PageRequest };
export { DEFAULT_SIZE, MAX_SIZE, PAGE_SIZES, pageSchema };
