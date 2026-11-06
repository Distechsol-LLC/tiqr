import { z } from 'zod';

import { currencySchema } from '$/catalog.ts';
import { modeSchema } from '$/settings.ts';

// What GET /api/branding sends: the install's name, look, languages, currencies and mode
const brandingSchema = z.object({
  app_name: z.string(),
  currencies: z.array(currencySchema),
  has_logo: z.boolean(),
  languages: z.array(z.string()),
  // A server from before the modes sends none, and only issued tickets
  mode: modeSchema.default('ticket'),
  theme: z.string(),
});

type Branding = z.infer<typeof brandingSchema>;

export type { Branding };
export { brandingSchema };
