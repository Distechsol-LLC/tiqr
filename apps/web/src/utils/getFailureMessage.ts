import {
  ERROR_INVALID_CREDENTIALS,
  ERROR_NETWORK,
  ERROR_RATE_LIMITED,
  ERROR_SERVER,
} from '@/config/errors.ts';
import type { ApiFailure } from '%/api.ts';

const SECONDS_PER_MINUTE = 60;

const formatWait = (seconds: number): string => {
  if (seconds < SECONDS_PER_MINUTE) return seconds === 1 ? '1 second' : `${seconds} seconds`;

  const minutes = Math.ceil(seconds / SECONDS_PER_MINUTE);

  return minutes === 1 ? '1 minute' : `${minutes} minutes`;
};

export const getFailureMessage = (failure: ApiFailure): string => {
  switch (failure.kind) {
    case 'unauthenticated':
      return ERROR_INVALID_CREDENTIALS;
    case 'rate_limited':
      return failure.retryAfter
        ? `Too many failed sign-ins. Try again in ${formatWait(failure.retryAfter)}.`
        : ERROR_RATE_LIMITED;
    case 'network':
      return ERROR_NETWORK;
    case 'invalid_response':
    case 'server':
      return ERROR_SERVER;
    default:
      return failure satisfies never;
  }
};
