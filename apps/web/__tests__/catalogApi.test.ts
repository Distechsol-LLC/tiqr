import { describe, expect, test as it } from 'bun:test';

import {
  createTicketType,
  createVisitorType,
  deleteTicketType,
  deleteVisitorType,
  fetchAllTicketTypes,
  fetchAllVisitorTypes,
  fetchTicketTypes,
  fetchVisitorTypes,
  updateTicketType,
  updateVisitorType,
} from '%/api.ts';
import { createVisitorSubtype, deleteVisitorSubtype, updateVisitorSubtype } from '%/subtypeApi.ts';
import { mockFetch, session } from '../__mocks__/api.ts';

const ID = '1f6a2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f';
const OTHER_ID = '2f6a2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f';
const day = { currency: 'USD' as const, id: ID, name: 'Day', price_minor: 1250 };
const SUBTYPE_ID = '3f6a2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f';
const pupil = { discount_percent: 30, id: SUBTYPE_ID, name: 'Pupil', visitor_type_id: ID };
const student = { id: ID, name: 'Student', subtypes: [pupil] };
const MAX_SIZE = 100;
const TWO = 2;
const THREE = 3;
const FRACTION = 12.5;
const FIRST_PAGE = { page: 1, size: 10 };
const CSRF = session.csrf_token;

type Item = { id: string; name: string };

const page = <Row extends Item>(
  items: Row[],
  total = items.length
): { items: Row[]; page: number; size: number; total: number } => ({
  items,
  page: 1,
  size: MAX_SIZE,
  total,
});

describe('catalog api', () => {
  it('reads a page of ticket types and of visitor types', async () => {
    const fetchMock = mockFetch(Response.json(page([day])), Response.json(page([student])));

    expect(await fetchTicketTypes(FIRST_PAGE)).toEqual({ data: page([day]), ok: true });
    expect(await fetchVisitorTypes(FIRST_PAGE)).toEqual({ data: page([student]), ok: true });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/ticket-types?page=1&size=10',
      '/api/visitor-types?page=1&size=10',
    ]);
  });

  it('refuses a ticket type whose price is not whole minor units', async () => {
    mockFetch(Response.json(page([{ ...day, price_minor: FRACTION }])));

    expect(await fetchTicketTypes(FIRST_PAGE)).toEqual({
      error: { kind: 'invalid_response' },
      ok: false,
    });
  });

  it('reads every ticket type and visitor type, a page at a time', async () => {
    const fetchMock = mockFetch(
      Response.json(page([day], TWO)),
      Response.json(page([{ ...day, id: OTHER_ID }], TWO)),
      Response.json(page([student]))
    );

    const ticketTypes = await fetchAllTicketTypes();
    const visitorTypes = await fetchAllVisitorTypes();

    expect(ticketTypes.ok && ticketTypes.data.map(({ id }) => id)).toEqual([ID, OTHER_ID]);
    expect(visitorTypes.ok && visitorTypes.data).toEqual([student]);
    expect(fetchMock).toHaveBeenCalledTimes(THREE);
  });

  it('creates and updates a ticket type with the CSRF token', async () => {
    const fetchMock = mockFetch(Response.json(day, { status: 201 }), Response.json(day));
    const fields = { currency: 'USD' as const, name: 'Day', price_minor: 1250 };

    expect(await createTicketType(CSRF, fields)).toEqual({ data: day, ok: true });
    expect(await updateTicketType(CSRF, ID, { price_minor: 1250 })).toEqual({
      data: day,
      ok: true,
    });

    const [[createUrl, create], [updateUrl, update]] = fetchMock.mock.calls as [
      [string, RequestInit],
      [string, RequestInit],
    ];

    expect(createUrl).toBe('/api/ticket-types');
    expect(create.method).toBe('POST');
    expect(create.body).toBe(JSON.stringify(fields));
    expect(new Headers(create.headers).get('X-CSRF-Token')).toBe(CSRF);
    expect(updateUrl).toBe(`/api/ticket-types/${ID}`);
    expect(update.method).toBe('PATCH');
    expect(update.body).toBe(JSON.stringify({ price_minor: 1250 }));
  });

  it('creates and updates a visitor type with the CSRF token', async () => {
    const fetchMock = mockFetch(Response.json(student, { status: 201 }), Response.json(student));
    const fields = { name: 'Student' };

    expect(await createVisitorType(CSRF, fields)).toEqual({ data: student, ok: true });
    expect(await updateVisitorType(CSRF, ID, { name: 'Student' })).toEqual({
      data: student,
      ok: true,
    });

    const [[createUrl, create], [updateUrl, update]] = fetchMock.mock.calls as [
      [string, RequestInit],
      [string, RequestInit],
    ];

    expect(createUrl).toBe('/api/visitor-types');
    expect(create.body).toBe(JSON.stringify(fields));
    expect(new Headers(update.headers).get('X-CSRF-Token')).toBe(CSRF);
    expect(updateUrl).toBe(`/api/visitor-types/${ID}`);
    expect(update.method).toBe('PATCH');
  });

  it('deletes either kind of type', async () => {
    const fetchMock = mockFetch(
      new Response(null, { status: 204 }),
      new Response(null, { status: 204 })
    );

    expect(await deleteTicketType(CSRF, ID)).toEqual({ data: null, ok: true });
    expect(await deleteVisitorType(CSRF, ID)).toEqual({ data: null, ok: true });

    const calls = fetchMock.mock.calls as [string, RequestInit][];

    expect(calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
      `DELETE /api/ticket-types/${ID}`,
      `DELETE /api/visitor-types/${ID}`,
    ]);
  });

  it('passes on a refusal with its message', async () => {
    mockFetch(
      Response.json(
        { code: 'invalid', detail: 'A ticket type with this name already exists' },
        { status: 422 }
      )
    );

    expect(await createTicketType(CSRF, { currency: 'USD', name: 'Day', price_minor: 1 })).toEqual({
      error: {
        code: 'invalid',
        detail: 'A ticket type with this name already exists',
        kind: 'server',
        status: 422,
      },
      ok: false,
    });
  });
});

describe('visitor subtype api', () => {
  it('creates, updates and deletes a visitor subtype under its type', async () => {
    const fetchMock = mockFetch(
      Response.json(pupil, { status: 201 }),
      Response.json(pupil),
      new Response(null, { status: 204 })
    );
    const fields = { discount_percent: 30, name: 'Pupil' };

    expect(await createVisitorSubtype(CSRF, ID, fields)).toEqual({ data: pupil, ok: true });
    expect(await updateVisitorSubtype(CSRF, ID, SUBTYPE_ID, { discount_percent: 30 })).toEqual({
      data: pupil,
      ok: true,
    });
    expect(await deleteVisitorSubtype(CSRF, ID, SUBTYPE_ID)).toEqual({ data: null, ok: true });

    const calls = fetchMock.mock.calls as [string, RequestInit][];

    expect(calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
      `POST /api/visitor-types/${ID}/subtypes`,
      `PATCH /api/visitor-types/${ID}/subtypes/${SUBTYPE_ID}`,
      `DELETE /api/visitor-types/${ID}/subtypes/${SUBTYPE_ID}`,
    ]);
    expect(calls[0]?.[1].body).toBe(JSON.stringify(fields));
    expect(new Headers(calls[2]?.[1].headers).get('X-CSRF-Token')).toBe(CSRF);
  });
});
