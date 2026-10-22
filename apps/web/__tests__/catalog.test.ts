import { afterEach, beforeEach, describe, expect, test as it } from 'bun:test';

import { az } from '@/locales/az.ts';
import { en } from '@/locales/en.ts';
import { i18n } from '%/useLocale.svelte.ts';
import {
  ticketTypeInputSchema,
  ticketTypeSchema,
  visitorTypeInputSchema,
  visitorTypeSchema,
} from '$/catalog.ts';
import { ticketInputSchema } from '$/tickets.ts';

const FRACTION = 1.5;
const OVER = 101;
const FULL = 100;
const OVER_LONG = 201;
const ID = '1f6a2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f';

describe('catalog', () => {
  beforeEach(() => {
    i18n.set('en');
  });

  afterEach(() => {
    i18n.set('en');
  });

  it('reads types as the API sends them', () => {
    expect(
      ticketTypeSchema.safeParse({ currency: 'AZN', id: ID, name: 'Day', price_minor: 1250 })
        .success
    ).toBeTrue();
    expect(
      visitorTypeSchema.safeParse({ discount_percent: 30, id: ID, name: 'Student' }).success
    ).toBeTrue();
  });

  it('refuses a price or discount the API would not send', () => {
    expect(
      ticketTypeSchema.safeParse({ currency: 'USD', id: ID, name: 'Day', price_minor: -1 }).success
    ).toBeFalse();
    expect(
      ticketTypeSchema.safeParse({ currency: 'USD', id: ID, name: 'Day', price_minor: FRACTION })
        .success
    ).toBeFalse();
    expect(
      visitorTypeSchema.safeParse({ discount_percent: OVER, id: ID, name: 'Student' }).success
    ).toBeFalse();
  });

  it('turns a typed ticket type into what the API takes', () => {
    expect(
      ticketTypeInputSchema.parse({ currency: 'RUB', name: '  Day pass ', price: '12,5' })
    ).toEqual({ currency: 'RUB', name: 'Day pass', price: 1250 });
  });

  it('refuses a ticket type without a currency, or with one the API does not take', () => {
    for (const currency of ['', 'EUR']) {
      const result = ticketTypeInputSchema.safeParse({ currency, name: 'Day', price: '1' });

      expect(result.error?.issues[0]?.message).toBe(en.errors.currencyRequired);
    }
  });

  it('refuses a blank name and a bad or oversized price', () => {
    const blank = ticketTypeInputSchema.safeParse({ currency: 'USD', name: '  ', price: '1' });
    const bad = ticketTypeInputSchema.safeParse({ currency: 'USD', name: 'Day', price: 'free' });
    const huge = ticketTypeInputSchema.safeParse({
      currency: 'USD',
      name: 'Day',
      price: '10000000.01',
    });
    const long = ticketTypeInputSchema.safeParse({
      currency: 'USD',
      name: 'x'.repeat(OVER_LONG),
      price: '1',
    });

    expect(blank.error?.issues[0]?.message).toBe(en.errors.nameRequired);
    expect(bad.error?.issues[0]?.message).toBe(en.errors.priceInvalid);
    expect(huge.error?.issues[0]?.message).toBe(en.errors.priceInvalid);
    expect(long.error?.issues[0]?.message).toBe(en.errors.nameLong);
    // The limit itself is fine
    expect(
      ticketTypeInputSchema.safeParse({ currency: 'USD', name: 'Day', price: '10000000' }).success
    ).toBeTrue();
  });

  it('turns a typed visitor type into what the API takes', () => {
    expect(visitorTypeInputSchema.parse({ discount: ' 30 ', name: ' Student ' })).toEqual({
      discount: 30,
      name: 'Student',
    });
    expect(visitorTypeInputSchema.parse({ discount: '0', name: 'Guest' }).discount).toBe(0);
    expect(visitorTypeInputSchema.parse({ discount: '100', name: 'Guest' }).discount).toBe(FULL);
  });

  it('refuses a discount that is not a whole number from 0 to 100', () => {
    for (const discount of ['', '101', '-1', '2.5', 'ten', '1000']) {
      const result = visitorTypeInputSchema.safeParse({ discount, name: 'Student' });

      expect(result.error?.issues[0]?.message).toBe(en.errors.discountInvalid);
    }
  });

  it('words refusals in the language showing at parse time', () => {
    i18n.set('az');

    const result = ticketTypeInputSchema.safeParse({ currency: 'USD', name: '', price: 'free' });

    expect(result.error?.issues.map((issue) => issue.message)).toEqual([
      az.errors.nameRequired,
      az.errors.priceInvalid,
    ]);
  });

  it('leaves the ticket type out of a ticket unless one is picked', () => {
    const base = {
      usage_type: 'one_time',
      valid_from: '2030-06-01T09:00',
      valid_until: '2030-06-01T18:00',
      visitor_name: 'Ada',
      visitor_type: 'Guest',
    };

    expect(ticketInputSchema.parse({ ...base, ticket_type: '' }).ticket_type).toBeUndefined();
    expect(ticketInputSchema.parse({ ...base, ticket_type: ' Day pass ' }).ticket_type).toBe(
      'Day pass'
    );
  });
});
