import { describe, expect, test as it } from 'bun:test';

import {
  ERROR_INVALID_CREDENTIALS,
  ERROR_NETWORK,
  ERROR_RATE_LIMITED,
  ERROR_SERVER,
} from '@/config/errors.ts';
import { getFailureMessage } from '%/getFailureMessage.ts';

describe('getFailureMessage', () => {
  it('explains wrong credentials', () => {
    expect(getFailureMessage({ kind: 'unauthenticated' })).toBe(ERROR_INVALID_CREDENTIALS);
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

  it('falls back when the wait is unknown', () => {
    expect(getFailureMessage({ kind: 'rate_limited', retryAfter: null })).toBe(ERROR_RATE_LIMITED);
  });

  it('explains network and server failures', () => {
    expect(getFailureMessage({ kind: 'network' })).toBe(ERROR_NETWORK);
    expect(getFailureMessage({ code: 'internal', kind: 'server', status: 500 })).toBe(ERROR_SERVER);
    expect(getFailureMessage({ kind: 'invalid_response' })).toBe(ERROR_SERVER);
  });
});
