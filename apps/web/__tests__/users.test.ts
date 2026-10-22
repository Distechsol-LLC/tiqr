import { beforeEach, describe, expect, test as it } from 'bun:test';

import { i18n } from '%/useLocale.svelte.ts';
import { passwordResetSchema, userInputSchema, userPatchSchema } from '$/users.ts';

const PASSWORD_LIMIT = 1024;

describe('user schemas', () => {
  beforeEach(() => {
    i18n.set('en');
  });

  it('accepts a complete new account and trims the username', () => {
    const parsed = userInputSchema.parse({
      password: 'correct-password',
      role: 'operator',
      username: '  leyla  ',
    });

    expect(parsed).toEqual({ password: 'correct-password', role: 'operator', username: 'leyla' });
  });

  it('reports a blank username in the showing language', () => {
    const result = userInputSchema.safeParse({
      password: 'correct-password',
      role: 'operator',
      username: '   ',
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(['username']);
    expect(result.error?.issues[0]?.message).toBe('Enter your username.');
  });

  it('rejects an unknown role', () => {
    expect(
      userInputSchema.safeParse({ password: 'correct-password', role: 'root', username: 'eve' })
        .success
    ).toBe(false);
  });

  it('rejects a password that is only whitespace', () => {
    const result = passwordResetSchema.safeParse({ password: '    ' });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe('Enter your password.');
  });

  it('rejects a password over the server limit of 1024 characters', () => {
    expect(
      passwordResetSchema.safeParse({ password: 'x'.repeat(PASSWORD_LIMIT + 1) }).success
    ).toBe(false);
    expect(passwordResetSchema.safeParse({ password: 'x'.repeat(PASSWORD_LIMIT) }).success).toBe(
      true
    );
  });

  it('accepts an empty patch, since omitted fields stay as they are', () => {
    expect(userPatchSchema.parse({})).toEqual({});
  });

  it('accepts a patch that changes only the status', () => {
    expect(userPatchSchema.parse({ active: false })).toEqual({ active: false });
  });

  it('rejects a patch with a non-boolean status or an unknown role', () => {
    expect(userPatchSchema.safeParse({ active: 'no' }).success).toBe(false);
    expect(userPatchSchema.safeParse({ role: 'root' }).success).toBe(false);
  });
});
