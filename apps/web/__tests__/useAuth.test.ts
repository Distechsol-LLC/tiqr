import { describe, expect, test as it } from 'bun:test';

import { createAuth } from '%/useAuth.svelte.ts';
import { mockFetch, session } from '../__mocks__/api.ts';

const credentials = { password: 'secret', username: 'clerk' };

describe('useAuth', () => {
  it('restores a live session once', async () => {
    const fetchMock = mockFetch(Response.json(session));
    const auth = createAuth();

    await Promise.all([auth.restore(), auth.restore()]);

    expect(auth.session).toEqual(session);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('stays signed out without a session cookie', async () => {
    mockFetch(Response.json({ code: 'unauthenticated', detail: 'Not signed in' }, { status: 401 }));
    const auth = createAuth();

    await auth.restore();

    expect(auth.session).toBeNull();
  });

  it('keeps the session after signing in', async () => {
    mockFetch(Response.json(session));
    const auth = createAuth();

    const result = await auth.signIn(credentials);

    expect(result.ok).toBeTrue();
    expect(auth.session).toEqual(session);
  });

  it('stays signed out when sign-in is refused', async () => {
    mockFetch(Response.json({ code: 'unauthenticated', detail: 'Invalid' }, { status: 401 }));
    const auth = createAuth();

    const result = await auth.signIn(credentials);

    expect(result.ok).toBeFalse();
    expect(auth.session).toBeNull();
  });

  it('forgets the session on sign-out even if the server is unreachable', async () => {
    const fetchMock = mockFetch(Response.json(session), new TypeError('Failed to fetch'));
    const auth = createAuth();

    await auth.signIn(credentials);
    await auth.signOut();

    expect(auth.session).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
