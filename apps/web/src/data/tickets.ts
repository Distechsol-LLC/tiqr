import { z } from 'zod';

import { i18n } from '%/useLocale.svelte.ts';
import { currencySchema } from '$/catalog.ts';

// Same bound as _Name in apps/api/src/tiqr/api/schemas.py
const NAME_MAX = 200;
// Same bound as _Discount in apps/api/src/tiqr/api/schemas.py
const DISCOUNT_MAX = 100;

const ticketStateSchema = z.enum(['issued', 'passed', 'expired']);
const usageTypeSchema = z.enum(['one_time', 'multi_use']);

const offsetDatetime = z.iso.datetime({ offset: true });

// Every datetime arrives already shifted into `timezone`, the server's TIQR_DEFAULT_TZ
const ticketSchema = z.object({
  assigned_operator: z.uuid(),
  // What the ticket was priced at when made; null for one made without a ticket type
  base_price_minor: z.number().int().nonnegative().nullable(),
  created_at: offsetDatetime,
  created_by: z.uuid(),
  // The currency that price was in; null with it
  currency: currencySchema.nullable(),
  discount_percent: z.number().int().min(0).max(DISCOUNT_MAX),
  id: z.uuid(),
  passed_at: offsetDatetime.nullable(),
  price_minor: z.number().int().nonnegative().nullable(),
  print_count: z.number().int().nonnegative(),
  readable_serial: z.string(),
  state: ticketStateSchema,
  ticket_type: z.string().nullable(),
  timezone: z.string(),
  usage_type: usageTypeSchema,
  use_count: z.number().int().nonnegative(),
  valid_from: offsetDatetime,
  valid_until: offsetDatetime,
  visitor_name: z.string(),
  visitor_type: z.string(),
});

// The form sends <input type="datetime-local"> values; the server reads them in its own zone.
// Both ends are inclusive, so an equal pair is a legal one-instant window.
// Messages are read at parse time, so they come out in the language showing then.
const ticketInputSchema = z
  .object({
    // Left out when blank: the API then makes an unpriced ticket
    ticket_type: z
      .string()
      .trim()
      .max(NAME_MAX, { error: () => i18n.t.errors.nameLong })
      .transform((name) => name || undefined)
      .optional(),
    usage_type: usageTypeSchema,
    valid_from: z.string().min(1, { error: () => i18n.t.errors.validFromRequired }),
    valid_until: z.string().min(1, { error: () => i18n.t.errors.validUntilRequired }),
    visitor_name: z
      .string()
      .trim()
      .min(1, { error: () => i18n.t.errors.visitorNameRequired })
      .max(NAME_MAX, { error: () => i18n.t.errors.visitorNameLong }),
    visitor_type: z
      .string()
      .trim()
      .min(1, { error: () => i18n.t.errors.visitorTypeRequired })
      .max(NAME_MAX, { error: () => i18n.t.errors.visitorTypeLong }),
  })
  // Same-format local strings compare in time order
  .refine(
    (input) => !(input.valid_from && input.valid_until) || input.valid_until >= input.valid_from,
    {
      error: () => i18n.t.errors.validUntilBefore,
      path: ['valid_until'],
    }
  );

const assignInputSchema = z.object({
  assignee: z.string().min(1, { error: () => i18n.t.errors.assigneeRequired }),
});

type AssignInput = z.infer<typeof assignInputSchema>;
type Ticket = z.infer<typeof ticketSchema>;
type TicketInput = z.infer<typeof ticketInputSchema>;
type TicketState = z.infer<typeof ticketStateSchema>;
type UsageType = z.infer<typeof usageTypeSchema>;

export type { AssignInput, Ticket, TicketInput, TicketState, UsageType };
export { assignInputSchema, ticketInputSchema, ticketSchema, ticketStateSchema, usageTypeSchema };
