import { describe, expect, test as it } from 'bun:test';

import { credentialsSchema, sessionSchema } from '$/auth.ts';
import { session } from '../__mocks__/api.ts';

// One past the limits in apps/api/src/tiqr/api/schemas.py
const USERNAME_TOO_LONG = 151;
const PASSWORD_TOO_LONG = 1025;

describe('credentialsSchema', () => {
  it('trims the username but keeps the password as typed', () => {
    const result = credentialsSchema.parse({ password: ' secret ', username: '  clerk ' });

    expect(result).toEqual({ password: ' secret ', username: 'clerk' });
  });

  it('refuses a blank username', () => {
    const result = credentialsSchema.safeParse({ password: 'secret', username: '   ' });

    expect(result.success).toBeFalse();
    expect(result.error?.issues[0]?.path).toEqual(['username']);
  });

  it('refuses a whitespace-only password', () => {
    const result = credentialsSchema.safeParse({ password: '  ', username: 'clerk' });

    expect(result.success).toBeFalse();
    expect(result.error?.issues[0]?.path).toEqual(['password']);
  });

  it('refuses values past the API limits', () => {
    expect(
      credentialsSchema.safeParse({ password: 'secret', username: 'a'.repeat(USERNAME_TOO_LONG) })
        .success
    ).toBeFalse();
    expect(
      credentialsSchema.safeParse({ password: 'a'.repeat(PASSWORD_TOO_LONG), username: 'clerk' })
        .success
    ).toBeFalse();
  });
});

describe('sessionSchema', () => {
  it('accepts a session from the API', () => {
    expect(sessionSchema.parse(session)).toEqual(session);
  });

  it('refuses an unknown role', () => {
    const result = sessionSchema.safeParse({ ...session, user: { ...session.user, role: 'root' } });

    expect(result.success).toBeFalse();
  });
});
