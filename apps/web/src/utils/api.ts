import { z } from 'zod';

import type { DateRange } from '%/statsRange.ts';
import {
  type Credentials,
  type Session,
  type User,
  apiErrorSchema,
  sessionSchema,
  userSchema,
} from '$/auth.ts';
import { type Config, type Stats, configSchema, countSchema, statsSchema } from '$/operations.ts';
import { MAX_SIZE, type Page, type PageRequest, pageSchema } from '$/pagination.ts';
import {
  type AssignInput,
  type Ticket,
  type TicketInput,
  type TicketState,
  ticketSchema,
} from '$/tickets.ts';
import type { UserInput, UserPatch } from '$/users.ts';

const API_BASE = '/api';
const CSRF_HEADER = 'X-CSRF-Token';
const UNAUTHENTICATED = 401;
const NO_CONTENT = 204;
const RATE_LIMITED = 429;

type ApiFailure =
  | { kind: 'invalid_response' }
  | { kind: 'network' }
  | { kind: 'rate_limited'; retryAfter: number | null }
  | { kind: 'server'; code: string | null; detail: string | null; status: number }
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

  // Core refusals carry a message meant for people; malformed-request lists don't
  return {
    code: body.success ? body.data.code : null,
    detail: body.success && typeof body.data.detail === 'string' ? body.data.detail : null,
    kind: 'server',
    status: response.status,
  };
};

const send = async (path: string, init: RequestInit): Promise<ApiResult<Response>> => {
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

  return response.ok
    ? { data: response, ok: true }
    : { error: await toFailure(response), ok: false };
};

const request = async <T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {}
): Promise<ApiResult<T>> => {
  const result = await send(path, init);

  if (!result.ok) return result;

  const body = schema.safeParse(await readJson(result.data));

  return body.success
    ? { data: body.data, ok: true }
    : { error: { kind: 'invalid_response' }, ok: false };
};

// Every write carries the session's CSRF token; the API refuses it otherwise
const write = (
  method: 'DELETE' | 'PATCH' | 'POST',
  csrfToken: string,
  body?: unknown
): RequestInit => ({
  body: body === undefined ? undefined : JSON.stringify(body),
  headers: {
    [CSRF_HEADER]: csrfToken,
    ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
  },
  method,
});

const login = (credentials: Credentials): Promise<ApiResult<Session>> =>
  request('/auth/login', sessionSchema, {
    body: JSON.stringify(credentials),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });

const fetchSession = (): Promise<ApiResult<Session>> => request('/auth/session', sessionSchema);

const logout = (csrfToken: string): Promise<ApiResult<null>> =>
  request('/auth/logout', z.null(), write('POST', csrfToken));

const fetchConfig = (): Promise<ApiResult<Config>> => request('/config', configSchema);

const pageQuery = ({ page, size }: PageRequest): URLSearchParams =>
  new URLSearchParams({ page: String(page), size: String(size) });

const fetchUsers = (paging: PageRequest): Promise<ApiResult<Page<User>>> =>
  request(`/users?${pageQuery(paging)}`, pageSchema(userSchema));

// Every account, a page at a time, for the screens that need the whole list
const fetchAllUsers = async (): Promise<ApiResult<User[]>> => {
  const users: User[] = [];

  for (let page = 1; ; page += 1) {
    // Pages are read in turn: the next one is only asked for if this one wasn't the last
    const result = await fetchUsers({ page, size: MAX_SIZE });

    if (!result.ok) return result;

    users.push(...result.data.items);

    if (result.data.items.length === 0 || users.length >= result.data.total)
      return { data: users, ok: true };
  }
};

const createUser = (csrfToken: string, input: UserInput): Promise<ApiResult<User>> =>
  request('/users', userSchema, write('POST', csrfToken, input));

const updateUser = (csrfToken: string, id: string, patch: UserPatch): Promise<ApiResult<User>> =>
  request(`/users/${id}`, userSchema, write('PATCH', csrfToken, patch));

// Only deactivated accounts without tickets; the API refuses the rest
const deleteUser = (csrfToken: string, id: string): Promise<ApiResult<null>> =>
  request(`/users/${id}`, z.null(), write('DELETE', csrfToken));

const fetchTickets = (
  paging: PageRequest,
  state?: TicketState
): Promise<ApiResult<Page<Ticket>>> => {
  const query = pageQuery(paging);

  if (state) query.set('state', state);

  return request(`/tickets?${query}`, pageSchema(ticketSchema));
};

const fetchTicket = (id: string): Promise<ApiResult<Ticket>> =>
  request(`/tickets/${id}`, ticketSchema);

const createTicket = (csrfToken: string, input: TicketInput): Promise<ApiResult<Ticket>> =>
  request('/tickets', ticketSchema, write('POST', csrfToken, input));

const assignTicket = (
  csrfToken: string,
  id: string,
  input: AssignInput
): Promise<ApiResult<Ticket>> =>
  request(`/tickets/${id}/assign`, ticketSchema, write('POST', csrfToken, input));

// A POST, since every render counts as a print
const renderTicketPdf = async (csrfToken: string, id: string): Promise<ApiResult<Blob>> => {
  const result = await send(`/tickets/${id}/pdf`, {
    ...write('POST', csrfToken),
    headers: { Accept: 'application/pdf', [CSRF_HEADER]: csrfToken },
  });

  if (!result.ok) return result;

  try {
    return { data: await result.data.blob(), ok: true };
  } catch {
    return { error: { kind: 'network' }, ok: false };
  }
};

const printTicket = (csrfToken: string, id: string): Promise<ApiResult<Ticket>> =>
  request(`/tickets/${id}/print`, ticketSchema, write('POST', csrfToken));

const runSync = (csrfToken: string): Promise<ApiResult<number>> =>
  request(
    '/sync',
    countSchema.transform(({ count }) => count),
    write('POST', csrfToken)
  );

const runCleanup = (csrfToken: string): Promise<ApiResult<number>> =>
  request(
    '/cleanup',
    countSchema.transform(({ count }) => count),
    write('POST', csrfToken)
  );

// Tickets created on these days, both ends inclusive, on the server's clock; without, every one
const fetchStats = (range?: DateRange): Promise<ApiResult<Stats>> =>
  request(range ? `/stats?${new URLSearchParams(range)}` : '/stats', statsSchema);

export type { ApiFailure, ApiResult };
export {
  assignTicket,
  createTicket,
  createUser,
  deleteUser,
  fetchAllUsers,
  fetchConfig,
  fetchSession,
  fetchStats,
  fetchTicket,
  fetchTickets,
  fetchUsers,
  login,
  logout,
  printTicket,
  renderTicketPdf,
  runCleanup,
  runSync,
  updateUser,
};
