import { afterEach, beforeEach, describe, expect, test as it } from 'bun:test';

import { az } from '@/locales/az.ts';
import { en } from '@/locales/en.ts';
import { i18n } from '%/useLocale.svelte.ts';
import {
  GROUP_MAX,
  parseTicketInput,
  parseVisitorCount,
  priceFor,
  ticketSchema,
} from '$/tickets.ts';
import { ticket } from '../__mocks__/api.ts';

// What the form holds; each mode reads the fields it has
const fields = {
  group_size: '',
  ticket_type: '',
  usage_type: 'one_time',
  valid_from: '2030-06-01T09:00',
  valid_until: '2030-06-01T09:00',
  visitor_name: '  Ada  ',
  visitor_type: 'Guest',
};

const badge = { ...fields, usage_type: 'multi_use' };

const PEOPLE = 3;
// A reissue's people as typed, and what each reads as
const COUNTS: [string, number][] = [
  [' 1 ', 1],
  [String(PEOPLE), PEOPLE],
  [String(GROUP_MAX), GROUP_MAX],
];
const BAD_COUNTS = ['', '0', '101', '2.5', 'two'];
// Half of 10.01, rounded half up, is 5.01 a person
const BASE = 1001;
const HALF = 50;
const PEOPLE_TOTAL = 1503;

describe('tickets', () => {
  beforeEach(() => {
    i18n.set('en');
  });

  afterEach(() => {
    i18n.set('en');
  });

  it('reads tickets with microsecond timestamps', () => {
    expect(ticketSchema.safeParse(ticket).success).toBeTrue();
  });

  it('reads one person for a ticket from before group tickets', () => {
    const { group_size: _, ...older } = ticket;

    expect(ticketSchema.parse(older).group_size).toBe(1);
  });

  it("accepts a one-instant window and trims a badge holder's name", () => {
    const result = parseTicketInput('badge', badge);

    expect(result.ok && 'visitor_name' in result.data && result.data.visitor_name).toBe('Ada');
  });

  it('refuses a reversed window', () => {
    const result = parseTicketInput('badge', { ...badge, valid_until: '2030-06-01T08:59' });

    expect(result.ok ? null : result.errors.valid_until).toEqual([en.errors.validUntilBefore]);
  });

  it('refuses a badge without a visitor name', () => {
    const result = parseTicketInput('badge', { ...badge, visitor_name: '   ' });

    expect(result.ok ? null : result.errors.visitor_name).toEqual([en.errors.visitorNameRequired]);
  });

  it('only issues multi-use badges', () => {
    expect(parseTicketInput('badge', fields).ok).toBeFalse();
  });

  it('sends a ticket without a name, for one person', () => {
    const result = parseTicketInput('ticket', fields);

    expect(result.ok && result.data).toEqual({
      group_size: 1,
      usage_type: 'one_time',
      valid_from: '2030-06-01T09:00',
      valid_until: '2030-06-01T09:00',
      visitor_type: 'Guest',
    });
  });

  it('sends a group ticket with its size', () => {
    const result = parseTicketInput('ticket', { ...fields, group_size: '10', usage_type: 'group' });

    expect(result.ok && 'group_size' in result.data && result.data.group_size).toBe(10);
  });

  it.each(['', '1', '101', '2.5'])('refuses a group of %p', (size) => {
    const result = parseTicketInput('ticket', { ...fields, group_size: size, usage_type: 'group' });

    expect(result.ok ? null : result.errors.group_size).toEqual([en.errors.groupSizeInvalid]);
  });

  it('never issues a multi-use ticket', () => {
    expect(parseTicketInput('ticket', badge).ok).toBeFalse();
  });

  it('words refusals in the language showing at parse time', () => {
    i18n.set('az');

    const result = parseTicketInput('badge', { ...badge, visitor_name: '   ' });

    expect(result.ok ? null : result.errors.visitor_name).toEqual([az.errors.visitorNameRequired]);
  });

  it("reads a reissue's people from one to the most a group admits", () => {
    expect(COUNTS.map(([text]) => parseVisitorCount(text))).toEqual(COUNTS.map(([, n]) => n));
    expect(BAD_COUNTS.map(parseVisitorCount).every((count) => count === null)).toBeTrue();
  });

  it('prices a ticket once a person, at its own discounted price', () => {
    const priced = { ...ticket, base_price_minor: BASE, currency: 'AZN', discount_percent: HALF };

    expect(priceFor(ticketSchema.parse(priced), PEOPLE)).toBe(PEOPLE_TOTAL);
    expect(priceFor(ticketSchema.parse(ticket), PEOPLE)).toBeNull();
  });
});
