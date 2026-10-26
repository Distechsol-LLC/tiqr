import { z } from 'zod';

const licenseStateSchema = z.enum(['active', 'expired', 'invalid', 'none']);
const licenseTypeSchema = z.enum(['standard', 'trial']);
const requestTypeSchema = z.enum(['standard', 'trial']);

const licenseStatusSchema = z.object({
  days_remaining: z.number().int().nonnegative().nullable(),
  expires_at: z.string().nullable(),
  is_valid: z.boolean(),
  licensed_to: z.string().nullable(),
  machine_id: z.string(),
  state: licenseStateSchema,
  type: licenseTypeSchema.nullable(),
});

const requestCodeSchema = z.object({ code: z.string() });

type LicenseStatus = z.infer<typeof licenseStatusSchema>;
type RequestType = z.infer<typeof requestTypeSchema>;

export type { LicenseStatus, RequestType };
export { licenseStatusSchema, requestCodeSchema, requestTypeSchema };
