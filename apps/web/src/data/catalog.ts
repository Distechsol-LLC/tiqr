import { z } from 'zod';

import { parseMinor } from '%/money.ts';
import { i18n } from '%/useLocale.svelte.ts';

// Same bounds as _Name, _Price and _Discount in apps/api/src/tiqr/api/schemas.py
const NAME_MAX = 200;
const PRICE_MAX = 1_000_000_000;
const DISCOUNT_MAX = 100;
// Whole per cent only, as the API takes it
const DISCOUNT_TEXT = /^\d{1,3}$/;

const ticketTypeSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  price_minor: z.number().int().nonnegative(),
});

const visitorTypeSchema = z.object({
  discount_percent: z.number().int().min(0).max(DISCOUNT_MAX),
  id: z.uuid(),
  name: z.string(),
});

const nameSchema = z
  .string()
  .trim()
  .min(1, { error: () => i18n.t.errors.nameRequired })
  .max(NAME_MAX, { error: () => i18n.t.errors.nameLong });

// The forms hold what was typed; parsing turns it into what the API takes.
// Messages are read at parse time, so they come out in the language showing then.
const ticketTypeInputSchema = z.object({
  name: nameSchema,
  price: z
    .string()
    .transform((text) => parseMinor(text))
    .refine((minor) => minor !== null && minor <= PRICE_MAX, {
      error: () => i18n.t.errors.priceInvalid,
    })
    .transform((minor) => minor as number),
});

const visitorTypeInputSchema = z.object({
  discount: z
    .string()
    .trim()
    .refine((text) => DISCOUNT_TEXT.test(text) && Number(text) <= DISCOUNT_MAX, {
      error: () => i18n.t.errors.discountInvalid,
    })
    .transform(Number),
  name: nameSchema,
});

type TicketType = z.infer<typeof ticketTypeSchema>;
type TicketTypeFields = { name: string; price_minor: number };
type VisitorType = z.infer<typeof visitorTypeSchema>;
type VisitorTypeFields = { discount_percent: number; name: string };

export type { TicketType, TicketTypeFields, VisitorType, VisitorTypeFields };
export { ticketTypeInputSchema, ticketTypeSchema, visitorTypeInputSchema, visitorTypeSchema };
