import { afterEach, beforeEach, describe, expect, test as it } from 'bun:test';

import { az } from '@/locales/az.ts';
import { en } from '@/locales/en.ts';
import { i18n } from '%/useLocale.svelte.ts';
import { ticketInputSchema, ticketSchema } from '$/tickets.ts';
import { ticket } from '../__mocks__/api.ts';

const input = {
  usage_type: 'multi_use',
  valid_from: '2030-06-01T09:00',
  valid_until: '2030-06-01T09:00',
  visitor_name: '  Ada  ',
  visitor_type: 'Guest',
};

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

  it('accepts a one-instant window and trims names', () => {
    expect(ticketInputSchema.parse(input).visitor_name).toBe('Ada');
  });

  it('refuses a reversed window', () => {
    const result = ticketInputSchema.safeParse({ ...input, valid_until: '2030-06-01T08:59' });

    expect(result.error?.issues[0]?.message).toBe(en.errors.validUntilBefore);
  });

  it('refuses a blank visitor name', () => {
    const result = ticketInputSchema.safeParse({ ...input, visitor_name: '   ' });

    expect(result.error?.issues[0]?.message).toBe(en.errors.visitorNameRequired);
  });

  it('words refusals in the language showing at parse time', () => {
    i18n.set('az');

    const result = ticketInputSchema.safeParse({ ...input, visitor_name: '   ' });

    expect(result.error?.issues[0]?.message).toBe(az.errors.visitorNameRequired);
  });
});
