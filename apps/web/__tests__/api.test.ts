import { describe, expect, test as it } from 'bun:test';

import {
  createTicket,
  fetchAllUsers,
  fetchSession,
  fetchStats,
  fetchTickets,
  fetchUsers,
  login,
  logout,
  renderTicketPdf,
  runSync,
  updateUser,
} from '%/api.ts';
import { mockFetch, session, ticket } from '../__mocks__/api.ts';

const FIRST_PAGE = { page: 1, size: 10 };
const credentials = { password: 'secret', username: 'clerk' };

describe('api sessions and errors', () => {
  it('login posts JSON and returns the session', async () => {
    const fetchMock = mockFetch(Response.json(session));

    const result = await login(credentials);

    expect(result).toEqual({ data: session, ok: true });

    const [url, init] = fetchMock.mock.calls[0] ?? [];

    expect(url).toBe('/api/auth/login');
    expect(init?.method).toBe('POST');
    expect(init?.credentials).toBe('same-origin');
    expect(init?.body).toBe(JSON.stringify(credentials));
  });

  it('login maps 401 to unauthenticated', async () => {
    mockFetch(Response.json({ code: 'unauthenticated', detail: 'Invalid' }, { status: 401 }));

    expect(await login(credentials)).toEqual({ error: { kind: 'unauthenticated' }, ok: false });
  });

  it('login reads Retry-After on 429', async () => {
    mockFetch(
      Response.json(
        { code: 'rate_limited', detail: 'Too many' },
        { headers: { 'Retry-After': '120' }, status: 429 }
      )
    );

    expect(await login(credentials)).toEqual({
      error: { kind: 'rate_limited', retryAfter: 120 },
      ok: false,
    });
  });

  it('ignores a malformed Retry-After', async () => {
    mockFetch(new Response(null, { headers: { 'Retry-After': 'soon' }, status: 429 }));

    expect(await login(credentials)).toEqual({
      error: { kind: 'rate_limited', retryAfter: null },
      ok: false,
    });
  });

  it('keeps the error code and message of other refusals', async () => {
    mockFetch(Response.json({ code: 'cross_origin', detail: 'Refused' }, { status: 403 }));

    expect(await login(credentials)).toEqual({
      error: { code: 'cross_origin', detail: 'Refused', kind: 'server', status: 403 },
      ok: false,
    });
  });

  it('drops the field list of a malformed request', async () => {
    mockFetch(
      Response.json({ detail: [{ loc: ['body'], msg: 'bad', type: 'x' }] }, { status: 422 })
    );

    expect(await fetchTickets(FIRST_PAGE)).toEqual({
      error: { code: null, detail: null, kind: 'server', status: 422 },
      ok: false,
    });
  });
});

describe('api reads', () => {
  it('asks for a page of tickets, optionally of one state', async () => {
    const page = { items: [ticket], page: 2, size: 5, total: 6 };
    const fetchMock = mockFetch(Response.json(page), Response.json(page));

    expect(await fetchTickets({ page: 2, size: 5 })).toEqual({ data: page, ok: true });
    expect(await fetchTickets({ page: 2, size: 5 }, 'issued')).toEqual({ data: page, ok: true });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/tickets?page=2&size=5',
      '/api/tickets?page=2&size=5&state=issued',
    ]);
  });

  it('refuses a list that is not a page', async () => {
    mockFetch(Response.json([ticket]));

    expect(await fetchTickets(FIRST_PAGE)).toEqual({
      error: { kind: 'invalid_response' },
      ok: false,
    });
  });

  it('reads every account, a page at a time', async () => {
    const accounts = Array.from({ length: 3 }, (_, index) => ({
      ...session.user,
      id: crypto.randomUUID(),
      username: `user${index}`,
    }));
    const fetchMock = mockFetch(
      Response.json({ items: accounts.slice(0, 2), page: 1, size: 100, total: 3 }),
      Response.json({ items: accounts.slice(2), page: 2, size: 100, total: 3 })
    );

    expect(await fetchAllUsers()).toEqual({ data: accounts, ok: true });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/users?page=1&size=100',
      '/api/users?page=2&size=100',
    ]);
  });

  it('fails when a page of accounts does', async () => {
    mockFetch(Response.json({ code: 'forbidden', detail: 'No' }, { status: 403 }));

    expect((await fetchUsers(FIRST_PAGE)).ok).toBe(false);
  });

  it('reads the statistics for all time or for a date range', async () => {
    const counts = { expired: 0, issued: 1, passed: 0, prints: 0, total: 1, uses: 0 };
    const stats = { ...counts, visitor_types: { Guest: counts } };
    const fetchMock = mockFetch(Response.json(stats), Response.json(stats));

    expect(await fetchStats()).toEqual({ data: stats, ok: true });
    expect(await fetchStats({ since: '2026-09-01', until: '2026-09-30' })).toEqual({
      data: stats,
      ok: true,
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/stats',
      '/api/stats?since=2026-09-01&until=2026-09-30',
    ]);
  });
});

describe('api writes', () => {
  it('creates a ticket with JSON and the CSRF token', async () => {
    const fetchMock = mockFetch(Response.json(ticket, { status: 201 }));
    const input = {
      usage_type: 'one_time',
      valid_from: '2030-06-01T09:00',
      valid_until: '2030-06-01T18:00',
      visitor_name: 'Ada',
      visitor_type: 'Guest',
    } as const;

    expect(await createTicket('csrf-token', input)).toEqual({ data: ticket, ok: true });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);

    expect(url).toBe('/api/tickets');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(JSON.stringify(input));
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('patches a user', async () => {
    const fetchMock = mockFetch(Response.json({ ...session.user, active: false }));

    const result = await updateUser('csrf-token', session.user.id, { active: false });

    expect(result).toEqual({ data: { ...session.user, active: false }, ok: true });
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('PATCH');
  });

  it('returns the rendered badge as a blob', async () => {
    mockFetch(new Response('%PDF-1.4', { headers: { 'Content-Type': 'application/pdf' } }));

    const result = await renderTicketPdf('csrf-token', ticket.id);

    expect(result.ok).toBeTrue();
    expect(result.ok && (await result.data.text())).toBe('%PDF-1.4');
  });

  it('unwraps sync counts', async () => {
    mockFetch(Response.json({ count: 3 }));

    expect(await runSync('csrf-token')).toEqual({ data: 3, ok: true });
  });

  it('reports a network failure', async () => {
    mockFetch(new TypeError('Failed to fetch'));

    expect(await fetchSession()).toEqual({ error: { kind: 'network' }, ok: false });
  });

  it('refuses a response that does not match the schema', async () => {
    mockFetch(Response.json({ ...session, csrf_token: '' }));

    expect(await fetchSession()).toEqual({ error: { kind: 'invalid_response' }, ok: false });
  });

  it('logout sends the CSRF token and accepts 204', async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }));

    expect(await logout('csrf-token')).toEqual({ data: null, ok: true });

    const [, init] = fetchMock.mock.calls[0] ?? [];

    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-token');
  });
});
