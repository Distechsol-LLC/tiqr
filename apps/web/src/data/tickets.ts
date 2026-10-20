import { z } from 'zod';

import {
  ERROR_ASSIGNEE_REQUIRED,
  ERROR_VALID_FROM_REQUIRED,
  ERROR_VALID_UNTIL_BEFORE,
  ERROR_VALID_UNTIL_REQUIRED,
  ERROR_VISITOR_NAME_LONG,
  ERROR_VISITOR_NAME_REQUIRED,
  ERROR_VISITOR_TYPE_LONG,
  ERROR_VISITOR_TYPE_REQUIRED,
} from '@/config/errors.ts';

// Same bound as _Name in apps/api/src/tiqr/api/schemas.py
const NAME_MAX = 200;

const ticketStateSchema = z.enum(['issued', 'passed', 'expired']);
const usageTypeSchema = z.enum(['one_time', 'multi_use']);

const offsetDatetime = z.iso.datetime({ offset: true });

// Every datetime arrives already shifted into `timezone`, the server's TIQR_DEFAULT_TZ
const ticketSchema = z.object({
  assigned_operator: z.uuid(),
  created_at: offsetDatetime,
  created_by: z.uuid(),
  id: z.uuid(),
  passed_at: offsetDatetime.nullable(),
  print_count: z.number().int().nonnegative(),
  readable_serial: z.string(),
  state: ticketStateSchema,
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
const ticketInputSchema = z
  .object({
    usage_type: usageTypeSchema,
    valid_from: z.string().min(1, ERROR_VALID_FROM_REQUIRED),
    valid_until: z.string().min(1, ERROR_VALID_UNTIL_REQUIRED),
    visitor_name: z
      .string()
      .trim()
      .min(1, ERROR_VISITOR_NAME_REQUIRED)
      .max(NAME_MAX, ERROR_VISITOR_NAME_LONG),
    visitor_type: z
      .string()
      .trim()
      .min(1, ERROR_VISITOR_TYPE_REQUIRED)
      .max(NAME_MAX, ERROR_VISITOR_TYPE_LONG),
  })
  // Same-format local strings compare in time order
  .refine(
    (input) => !(input.valid_from && input.valid_until) || input.valid_until >= input.valid_from,
    {
      message: ERROR_VALID_UNTIL_BEFORE,
      path: ['valid_until'],
    }
  );

const assignInputSchema = z.object({ assignee: z.string().min(1, ERROR_ASSIGNEE_REQUIRED) });

type AssignInput = z.infer<typeof assignInputSchema>;
type Ticket = z.infer<typeof ticketSchema>;
type TicketInput = z.infer<typeof ticketInputSchema>;
type TicketState = z.infer<typeof ticketStateSchema>;
type UsageType = z.infer<typeof usageTypeSchema>;

export type { AssignInput, Ticket, TicketInput, TicketState, UsageType };
export { assignInputSchema, ticketInputSchema, ticketSchema, ticketStateSchema, usageTypeSchema };
