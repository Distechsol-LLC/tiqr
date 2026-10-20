import { type Mock, spyOn } from 'bun:test';

import type { Session } from '$/auth.ts';

const session: Session = {
  csrf_token: 'csrf-token',
  expires_at: '2030-06-01T21:00:00+04:00',
  idle_timeout: 1800,
  user: {
    active: true,
    id: '0b9e6f1e-3f0a-4c55-9a8e-2d4b7c1f6a10',
    role: 'operator',
    username: 'clerk',
  },
};

const mockFetch = (...responses: (Error | Response)[]): Mock<typeof fetch> => {
  const fetchMock = spyOn(globalThis, 'fetch');

  for (const response of responses)
    if (response instanceof Error) fetchMock.mockRejectedValueOnce(response);
    else fetchMock.mockResolvedValueOnce(response);

  return fetchMock;
};

export { mockFetch, session };
