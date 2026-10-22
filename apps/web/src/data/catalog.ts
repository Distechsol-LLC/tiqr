import { z } from 'zod';

import { parseMinor } from '%/money.ts';
import { i18n } from '%/useLocale.svelte.ts';

// Same bounds as _Name, _Price and _Discount in apps/api/src/tiqr/api/schemas.py
const NAME_MAX = 200;
const PRICE_MAX = 1_000_000_000;
const DISCOUNT_MAX = 100;
// Whole per cent only, as the API takes it
const DISCOUNT_TEXT = /^\d{1,3}$/;

// The currencies the API takes, by the codes it sends
const CURRENCIES = ['USD', 'RUB', 'AZN'] as const;
const currencySchema = z.enum(CURRENCIES);

const ticketTypeSchema = z.object({
  currency: currencySchema,
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
  currency: z.enum(CURRENCIES, { error: () => i18n.t.errors.currencyRequired }),
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

type Currency = z.infer<typeof currencySchema>;
type TicketType = z.infer<typeof ticketTypeSchema>;
type TicketTypeFields = { currency: Currency; name: string; price_minor: number };
type VisitorType = z.infer<typeof visitorTypeSchema>;
type VisitorTypeFields = { discount_percent: number; name: string };

export type { Currency, TicketType, TicketTypeFields, VisitorType, VisitorTypeFields };
export {
  currencySchema,
  ticketTypeInputSchema,
  ticketTypeSchema,
  visitorTypeInputSchema,
  visitorTypeSchema,
};
