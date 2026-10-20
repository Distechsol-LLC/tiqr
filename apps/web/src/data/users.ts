import { z } from 'zod';

import { passwordSchema, roleSchema, usernameSchema } from '$/auth.ts';

const userInputSchema = z.object({
  password: passwordSchema,
  role: roleSchema,
  username: usernameSchema,
});

// Omitted fields stay as they are, as with UserPatch in apps/api/src/tiqr/api/schemas.py
const userPatchSchema = z
  .object({ active: z.boolean(), password: passwordSchema, role: roleSchema })
  .partial();

const passwordResetSchema = z.object({ password: passwordSchema });

type UserInput = z.infer<typeof userInputSchema>;
type UserPatch = z.infer<typeof userPatchSchema>;

export type { UserInput, UserPatch };
export { passwordResetSchema, userInputSchema };
