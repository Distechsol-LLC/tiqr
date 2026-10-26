import { z } from 'zod';

const configSchema = z.object({
  server_printing: z.boolean(),
  timezone: z.string(),
});

const countSchema = z.object({ count: z.number().int().nonnegative() });

const countsSchema = z.object({
  expired: z.number().int().nonnegative(),
  issued: z.number().int().nonnegative(),
  passed: z.number().int().nonnegative(),
  prints: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  uses: z.number().int().nonnegative(),
});

const statsSchema = countsSchema.extend({
  visitor_types: z.record(z.string(), countsSchema),
});

type Config = z.infer<typeof configSchema>;
type Counts = z.infer<typeof countsSchema>;
type Stats = z.infer<typeof statsSchema>;

// The same figures as `tiqr stats`, in its order; each is labelled in the showing language
const METRICS = [
  'total',
  'issued',
  'passed',
  'expired',
  'uses',
  'prints',
] satisfies (keyof Counts)[];

export type { Config, Counts, Stats };
export { METRICS, configSchema, countSchema, statsSchema };
