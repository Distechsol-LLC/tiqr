import type { ApiFailure } from '%/api.ts';
import { i18n } from '%/useLocale.svelte.ts';

const SECONDS_PER_MINUTE = 60;

const formatWait = (seconds: number): string => {
  if (seconds < SECONDS_PER_MINUTE) return i18n.t.errors.seconds(seconds);

  return i18n.t.errors.minutes(Math.ceil(seconds / SECONDS_PER_MINUTE));
};

export const getFailureMessage = (failure: ApiFailure): string => {
  const { errors } = i18n.t;

  switch (failure.kind) {
    case 'unauthenticated':
      return errors.invalidCredentials;
    case 'rate_limited':
      return failure.retryAfter
        ? errors.rateLimitedFor(formatWait(failure.retryAfter))
        : errors.rateLimited;
    case 'network':
      return errors.network;
    case 'invalid_response':
    case 'server':
      return errors.server;
    default:
      return failure satisfies never;
  }
};
