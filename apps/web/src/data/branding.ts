import { z } from 'zod';

import { currencySchema } from '$/catalog.ts';

// What GET /api/branding sends: the install's name, look, languages and currencies
const brandingSchema = z.object({
  app_name: z.string(),
  currencies: z.array(currencySchema),
  has_logo: z.boolean(),
  languages: z.array(z.string()),
  theme: z.string(),
});

type Branding = z.infer<typeof brandingSchema>;

export type { Branding };
export { brandingSchema };
