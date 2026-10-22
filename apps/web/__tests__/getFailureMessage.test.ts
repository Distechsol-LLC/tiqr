import { afterEach, beforeEach, describe, expect, test as it } from 'bun:test';

import { en } from '@/locales/en.ts';
import { ru } from '@/locales/ru.ts';
import { getFailureMessage } from '%/getFailureMessage.ts';
import { i18n } from '%/useLocale.svelte.ts';

describe('getFailureMessage', () => {
  beforeEach(() => {
    i18n.set('en');
  });

  afterEach(() => {
    i18n.set('en');
  });

  it('explains wrong credentials', () => {
    expect(getFailureMessage({ kind: 'unauthenticated' })).toBe(en.errors.invalidCredentials);
  });

  // biome-ignore-start lint/style/noMagicNumbers: a table of waits in seconds
  it.each([
    [1, '1 second'],
    [45, '45 seconds'],
    [60, '1 minute'],
    [61, '2 minutes'],
    [900, '15 minutes'],
    // biome-ignore-end lint/style/noMagicNumbers: a table of waits in seconds
  ])('rounds a %i second wait up to "%s"', (retryAfter, wait) => {
    expect(getFailureMessage({ kind: 'rate_limited', retryAfter })).toBe(
      `Too many failed sign-ins. Try again in ${wait}.`
    );
  });

  // biome-ignore-start lint/style/noMagicNumbers: a table of waits in seconds
  it.each([
    [1, '1 секунду'],
    [3, '3 секунды'],
    [45, '45 секунд'],
    [61, '2 минуты'],
    [900, '15 минут'],
    // biome-ignore-end lint/style/noMagicNumbers: a table of waits in seconds
  ])('words a %i second wait in Russian as "%s"', (retryAfter, wait) => {
    i18n.set('ru');

    expect(getFailureMessage({ kind: 'rate_limited', retryAfter })).toBe(
      ru.errors.rateLimitedFor(wait)
    );
  });

  it('falls back when the wait is unknown', () => {
    expect(getFailureMessage({ kind: 'rate_limited', retryAfter: null })).toBe(
      en.errors.rateLimited
    );
  });

  it('explains network and server failures', () => {
    expect(getFailureMessage({ kind: 'network' })).toBe(en.errors.network);
    expect(getFailureMessage({ code: 'internal', detail: null, kind: 'server', status: 500 })).toBe(
      en.errors.server
    );
    expect(getFailureMessage({ kind: 'invalid_response' })).toBe(en.errors.server);
  });

  it('speaks the chosen language', () => {
    i18n.set('ru');

    expect(getFailureMessage({ kind: 'network' })).toBe(ru.errors.network);
  });
});
