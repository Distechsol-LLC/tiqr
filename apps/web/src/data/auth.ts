import { z } from 'zod';

import {
  ERROR_PASSWORD_LONG,
  ERROR_PASSWORD_REQUIRED,
  ERROR_USERNAME_LONG,
  ERROR_USERNAME_REQUIRED,
} from '@/config/errors.ts';

// Same bounds as LoginIn in apps/api/src/tiqr/api/schemas.py
const USERNAME_MAX = 150;
const PASSWORD_MAX = 1024;

const credentialsSchema = z.object({
  // The core strips only the username, so the password goes out exactly as typed
  password: z
    .string()
    .max(PASSWORD_MAX, ERROR_PASSWORD_LONG)
    .refine((password) => password.trim().length > 0, ERROR_PASSWORD_REQUIRED),
  username: z
    .string()
    .trim()
    .min(1, ERROR_USERNAME_REQUIRED)
    .max(USERNAME_MAX, ERROR_USERNAME_LONG),
});

const userSchema = z.object({
  active: z.boolean(),
  id: z.uuid(),
  role: z.enum(['admin', 'manager', 'operator']),
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
type Session = z.infer<typeof sessionSchema>;

export type { Credentials, Session };
export { apiErrorSchema, credentialsSchema, sessionSchema };
