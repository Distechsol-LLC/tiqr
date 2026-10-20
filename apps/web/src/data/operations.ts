import { z } from 'zod';

const configSchema = z.object({
  server_printing: z.boolean(),
  timezone: z.string(),
});

const countSchema = z.object({ count: z.number().int().nonnegative() });

const statsSchema = z.object({
  expired: z.number().int().nonnegative(),
  issued: z.number().int().nonnegative(),
  passed: z.number().int().nonnegative(),
  prints: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  uses: z.number().int().nonnegative(),
});

type Config = z.infer<typeof configSchema>;
type Stats = z.infer<typeof statsSchema>;

export type { Config, Stats };
export { configSchema, countSchema, statsSchema };
