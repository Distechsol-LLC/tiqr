import { type ApiResult, fetchSession, login, logout } from '%/api.ts';
import type { Credentials, Session } from '$/auth.ts';

type AuthController = {
  readonly session: Session | null;
  restore: () => Promise<void>;
  signIn: (credentials: Credentials) => Promise<ApiResult<Session>>;
  signOut: () => Promise<void>;
};

// The CSRF token stays in memory; a reload gets it back from the session cookie
const createAuth = (): AuthController => {
  let session = $state<Session | null>(null);
  let restoring: Promise<void> | null = null;

  return {
    restore: (): Promise<void> => {
      restoring ??= fetchSession().then((result) => {
        if (result.ok) session = result.data;
      });

      return restoring;
    },
    get session(): Session | null {
      return session;
    },
    signIn: async (credentials: Credentials): Promise<ApiResult<Session>> => {
      const result = await login(credentials);

      if (result.ok) session = result.data;

      return result;
    },
    signOut: async (): Promise<void> => {
      if (!session) return;

      const { csrf_token } = session;

      // Forget the session even if the server is unreachable; the cookie expires on its own
      session = null;
      await logout(csrf_token);
    },
  };
};

const auth = createAuth();

export { auth, createAuth };
