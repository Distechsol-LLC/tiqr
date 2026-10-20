import { ERROR_SESSION_ENDED } from '@/config/errors.ts';
import { navigate } from '@/router.ts';
import type { ApiFailure } from '%/api.ts';
import { getFailureMessage } from '%/getFailureMessage.ts';
import { toaster } from '%/toaster.ts';
import { auth } from '%/useAuth.svelte.ts';

// Signed-in requests: show the server's own refusal, and send an ended session to sign-in
export const notifyFailure = async (title: string, failure: ApiFailure): Promise<void> => {
  if (failure.kind === 'unauthenticated') {
    toaster.error({ description: ERROR_SESSION_ENDED, title });
    auth.expire();
    await navigate('/login', { replace: true });
    return;
  }

  const detail = failure.kind === 'server' ? failure.detail : null;

  toaster.error({ description: detail ?? getFailureMessage(failure), title });
};
