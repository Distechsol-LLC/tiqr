import { z } from 'zod';

import { i18n } from '%/useLocale.svelte.ts';

// Same bounds as LoginIn in apps/api/src/tiqr/api/schemas.py
const USERNAME_MAX = 150;
const PASSWORD_MAX = 1024;

// Messages are read at parse time, so they come out in the language showing then
const passwordSchema = z
  .string()
  .max(PASSWORD_MAX, { error: () => i18n.t.errors.passwordLong })
  .refine((password) => password.trim().length > 0, {
    error: () => i18n.t.errors.passwordRequired,
  });

const usernameSchema = z
  .string()
  .trim()
  .min(1, { error: () => i18n.t.errors.usernameRequired })
  .max(USERNAME_MAX, { error: () => i18n.t.errors.usernameLong });

const credentialsSchema = z.object({
  // The core strips only the username, so the password goes out exactly as typed
  password: passwordSchema,
  username: usernameSchema,
});

const roleSchema = z.enum(['admin', 'manager', 'operator']);

const userSchema = z.object({
  active: z.boolean(),
  id: z.uuid(),
  role: roleSchema,
  username: z.string(),
});

const sessionSchema = z.object({
  csrf_token: z.string().min(1),
  expires_at: z.iso.datetime({ offset: true }),
  idle_timeout: z.number().int().positive(),
  user: userSchema,
});

const apiErrorSchema = z.object({
  code: z.string(),
  detail: z.unknown(),
});

type Credentials = z.infer<typeof credentialsSchema>;
type Role = z.infer<typeof roleSchema>;
type Session = z.infer<typeof sessionSchema>;
type User = z.infer<typeof userSchema>;

export type { Credentials, Role, Session, User };
export {
  apiErrorSchema,
  credentialsSchema,
  passwordSchema,
  roleSchema,
  sessionSchema,
  userSchema,
  usernameSchema,
};
