import { z } from 'zod';

import { type Credentials, type Session, apiErrorSchema, sessionSchema } from '$/auth.ts';

const API_BASE = '/api';
const CSRF_HEADER = 'X-CSRF-Token';
const UNAUTHENTICATED = 401;
const NO_CONTENT = 204;
const RATE_LIMITED = 429;

type ApiFailure =
  | { kind: 'invalid_response' }
  | { kind: 'network' }
  | { kind: 'rate_limited'; retryAfter: number | null }
  | { kind: 'server'; code: string | null; status: number }
  | { kind: 'unauthenticated' };

type ApiResult<T> = { data: T; ok: true } | { error: ApiFailure; ok: false };

const parseRetryAfter = (header: string | null): number | null => {
  const seconds = Number(header);

  return header && Number.isInteger(seconds) && seconds >= 0 ? seconds : null;
};

const readJson = async (response: Response): Promise<unknown> => {
  if (response.status === NO_CONTENT) return null;

  try {
    return await response.json();
  } catch {
    return undefined;
  }
};

const toFailure = async (response: Response): Promise<ApiFailure> => {
  if (response.status === UNAUTHENTICATED) return { kind: 'unauthenticated' };

  if (response.status === RATE_LIMITED)
    return {
      kind: 'rate_limited',
      retryAfter: parseRetryAfter(response.headers.get('Retry-After')),
    };

  const body = apiErrorSchema.safeParse(await readJson(response));

  return { code: body.success ? body.data.code : null, kind: 'server', status: response.status };
};

const request = async <T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {}
): Promise<ApiResult<T>> => {
  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // The session lives in an HTTP-only cookie the browser attaches on its own
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...init.headers },
    });
  } catch {
    return { error: { kind: 'network' }, ok: false };
  }

  if (!response.ok) return { error: await toFailure(response), ok: false };

  const body = schema.safeParse(await readJson(response));

  return body.success
    ? { data: body.data, ok: true }
    : { error: { kind: 'invalid_response' }, ok: false };
};

const login = (credentials: Credentials): Promise<ApiResult<Session>> =>
  request('/auth/login', sessionSchema, {
    body: JSON.stringify(credentials),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });

const fetchSession = (): Promise<ApiResult<Session>> => request('/auth/session', sessionSchema);

const logout = (csrfToken: string): Promise<ApiResult<null>> =>
  request('/auth/logout', z.null(), {
    headers: { [CSRF_HEADER]: csrfToken },
    method: 'POST',
  });

export type { ApiFailure, ApiResult };
export { fetchSession, login, logout };
