import { type Mock, spyOn } from 'bun:test';

import type { Session } from '$/auth.ts';
import type { Ticket } from '$/tickets.ts';

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

const ticket: Ticket = {
  assigned_operator: session.user.id,
  base_price_minor: null,
  created_at: '2030-05-31T12:00:00.123456+04:00',
  created_by: session.user.id,
  discount_percent: 0,
  id: '6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f',
  passed_at: null,
  price_minor: null,
  print_count: 0,
  readable_serial: 'TiQR-300531-00001',
  state: 'issued',
  ticket_type: null,
  timezone: 'Asia/Baku',
  usage_type: 'one_time',
  use_count: 0,
  valid_from: '2030-06-01T09:00:00+04:00',
  valid_until: '2030-06-01T18:00:00+04:00',
  visitor_name: 'Ada',
  visitor_type: 'Guest',
};

const mockFetch = (...responses: (Error | Response)[]): Mock<typeof fetch> => {
  const fetchMock = spyOn(globalThis, 'fetch');

  for (const response of responses)
    if (response instanceof Error) fetchMock.mockRejectedValueOnce(response);
    else fetchMock.mockResolvedValueOnce(response);

  return fetchMock;
};

export { mockFetch, session, ticket };
