import { describe, expect, test as it } from 'bun:test';

import { fetchSession, login, logout } from '%/api.ts';
import { mockFetch, session } from '../__mocks__/api.ts';

const credentials = { password: 'secret', username: 'clerk' };

describe('api', () => {
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

  it('keeps the error code of other refusals', async () => {
    mockFetch(Response.json({ code: 'cross_origin', detail: 'Refused' }, { status: 403 }));

    expect(await login(credentials)).toEqual({
      error: { code: 'cross_origin', kind: 'server', status: 403 },
      ok: false,
    });
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
