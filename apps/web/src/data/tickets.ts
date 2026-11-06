import { z } from 'zod';

import { discountedMinor } from '%/money.ts';
import { i18n } from '%/useLocale.svelte.ts';
import { currencySchema } from '$/catalog.ts';
import type { Mode } from '$/settings.ts';

// Same bound as _Name in apps/api/src/tiqr/api/schemas.py
const NAME_MAX = 200;
// Same bound as _Discount in apps/api/src/tiqr/api/schemas.py
const DISCOUNT_MAX = 100;
// Same bounds as MIN_GROUP_SIZE and MAX_GROUP_SIZE in apps/core/src/tiqr/core/models.py
const GROUP_MIN = 2;
const GROUP_MAX = 100;
const GROUP_TEXT = /^\d{1,4}$/;

const ticketStateSchema = z.enum(['issued', 'passed', 'expired', 'revoked']);
// A group ticket admits group_size people, once each
const usageTypeSchema = z.enum(['one_time', 'multi_use', 'group']);
// What each mode issues: badges are always multi-use; tickets admit once, or once per person
const TICKET_USAGES = ['one_time', 'group'] as const;

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
  // A server from before group tickets sends none, and every ticket admitted one person
  group_size: z.number().int().positive().default(1),
  id: z.uuid(),
  passed_at: offsetDatetime.nullable(),
  // What the whole ticket cost: a group pays the discounted price once per person
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
const windowFields = {
  valid_from: z.string().min(1, { error: () => i18n.t.errors.validFromRequired }),
  valid_until: z.string().min(1, { error: () => i18n.t.errors.validUntilRequired }),
};

const visitorTypeField = z
  .string()
  .trim()
  .min(1, { error: () => i18n.t.errors.visitorTypeRequired })
  .max(NAME_MAX, { error: () => i18n.t.errors.visitorTypeLong });

const visitorSubtypeField = z
  .string()
  .trim()
  .min(1, { error: () => i18n.t.errors.visitorSubtypeRequired })
  .max(NAME_MAX, { error: () => i18n.t.errors.visitorTypeLong });

// Same-format local strings compare in time order
const inOrder = (input: { valid_from: string; valid_until: string }): boolean =>
  !(input.valid_from && input.valid_until) || input.valid_until >= input.valid_from;

const ORDER_ISSUE = {
  error: (): string => i18n.t.errors.validUntilBefore,
  path: ['valid_until'],
};

// A badge names its visitor, has no price, and admits as often as its window allows
const badgeInputSchema = z
  .object({
    ...windowFields,
    usage_type: z.literal('multi_use'),
    visitor_name: z
      .string()
      .trim()
      .min(1, { error: () => i18n.t.errors.visitorNameRequired })
      .max(NAME_MAX, { error: () => i18n.t.errors.visitorNameLong }),
    visitor_type: visitorTypeField,
  })
  .refine(inOrder, ORDER_ISSUE);

// A ticket names no one; it admits once, or once per person of a group of `group_size`, which
// the form holds as typed
const ticketOnlyInputSchema = z
  .object({
    ...windowFields,
    group_size: z.string().trim(),
    // Left out when blank: the API then makes an unpriced ticket
    ticket_type: z
      .string()
      .trim()
      .max(NAME_MAX, { error: () => i18n.t.errors.nameLong })
      .transform((name) => name || undefined)
      .optional(),
    usage_type: z.enum(TICKET_USAGES),
    // The ticket carries its subtype in the type's place
    visitor_subtype: visitorSubtypeField,
    visitor_type: visitorTypeField,
  })
  .superRefine((input, ctx) => {
    const size = Number(input.group_size);

    if (
      input.usage_type === 'group' &&
      !(GROUP_TEXT.test(input.group_size) && size >= GROUP_MIN && size <= GROUP_MAX)
    )
      ctx.addIssue({
        code: 'custom',
        message: i18n.t.errors.groupSizeInvalid,
        path: ['group_size'],
      });
  })
  .refine(inOrder, ORDER_ISSUE)
  .transform(({ group_size: size, ...input }) => ({
    ...input,
    group_size: input.usage_type === 'group' ? Number(size) : 1,
  }));

// What POST /api/tickets takes, from either mode's form
type TicketInput = z.output<typeof badgeInputSchema> | z.output<typeof ticketOnlyInputSchema>;
// What the form holds, as typed; each mode reads the fields it has
type TicketFields = Record<
  | 'group_size'
  | 'ticket_type'
  | 'usage_type'
  | 'valid_from'
  | 'valid_until'
  | 'visitor_name'
  | 'visitor_subtype'
  | 'visitor_type',
  string
>;
type TicketParse =
  | { data: TicketInput; ok: true }
  | { errors: Partial<Record<keyof TicketFields, string[]>>; ok: false };

const toParse = <Output extends TicketInput>(result: z.ZodSafeParseResult<Output>): TicketParse =>
  result.success
    ? { data: result.data, ok: true }
    : { errors: z.flattenError(result.error).fieldErrors, ok: false };

// The form's fields as the mode's API checks them: what to send, or each field's refusals
const parseTicketInput = (mode: Mode, fields: TicketFields): TicketParse =>
  mode === 'badge'
    ? toParse(badgeInputSchema.safeParse(fields))
    : toParse(ticketOnlyInputSchema.safeParse(fields));

const assignInputSchema = z.object({
  assignee: z.string().min(1, { error: () => i18n.t.errors.assigneeRequired }),
});

// What the edit dialog sends: a new window; the API wants the end after the start
const editInputSchema = z
  .object({
    valid_from: z.string().min(1, { error: () => i18n.t.errors.validFromRequired }),
    valid_until: z.string().min(1, { error: () => i18n.t.errors.validUntilRequired }),
  })
  .refine((input) => input.valid_until > input.valid_from, {
    error: () => i18n.t.errors.validUntilBefore,
    path: ['valid_until'],
  });

// How many people a reissued ticket admits, as typed: one for one-time, more for a group
const parseVisitorCount = (text: string): number | null => {
  const count = Number(text.trim());

  return GROUP_TEXT.test(text.trim()) && count >= 1 && count <= GROUP_MAX ? count : null;
};

// Mirrors Ticket.price in apps/core/src/tiqr/core/models.py: the ticket's discounted price once
// for each of `people`; null for a ticket made without a ticket type
const priceFor = (ticket: Ticket, people: number): number | null =>
  ticket.base_price_minor === null
    ? null
    : discountedMinor(ticket.base_price_minor, ticket.discount_percent) * people;

type EditInput = z.infer<typeof editInputSchema>;
type AssignInput = z.infer<typeof assignInputSchema>;
type Ticket = z.infer<typeof ticketSchema>;
type TicketState = z.infer<typeof ticketStateSchema>;
type UsageType = z.infer<typeof usageTypeSchema>;

export type { AssignInput, EditInput, Ticket, TicketInput, TicketState, UsageType };
export {
  GROUP_MAX,
  GROUP_MIN,
  TICKET_USAGES,
  assignInputSchema,
  editInputSchema,
  parseTicketInput,
  parseVisitorCount,
  priceFor,
  ticketOnlyInputSchema,
  ticketSchema,
  ticketStateSchema,
};
