import { describe, expect, test as it } from 'bun:test';

import {
  CURRENCY_LABELS,
  discountedMinor,
  formatMinor,
  parseMinor,
  toPriceInput,
} from '%/money.ts';
import { i18n } from '%/useLocale.svelte.ts';

// biome-ignore-start lint/style/noMagicNumbers: the cases are the point
// Typed text and the minor units it stands for
const TYPED: [string, number][] = [
  ['12', 1200],
  ['12.5', 1250],
  ['12,50', 1250],
  [' 0.07 ', 7],
  ['0', 0],
];

// Not prices
const REFUSED = ['', ' ', 'abc', '-1', '1.234', '1.', '.5', '1,2,3', '1e3', '12 €'];

// Price, discount in per cent, and the price after it. The same cases as
// test_discount_rounds_half_up_in_minor_units in tests/core/test_catalog.py
const DISCOUNTS: [number, number, number][] = [
  [1000, 0, 1000],
  [1000, 25, 750],
  [1000, 100, 0],
  [999, 50, 500],
  [1, 50, 1],
  [0, 30, 0],
];

// biome-ignore-end lint/style/noMagicNumbers: the cases are the point

const TOO_BIG = '99999999999999999999';
const CENTS = 7;
const TWELVE_FIFTY = 1250;
const BIG = 123_456;

describe('money', () => {
  it('reads typed prices as whole minor units', () => {
    for (const [text, minor] of TYPED) expect(parseMinor(text)).toBe(minor);
  });

  it('refuses what is not a price', () => {
    for (const text of REFUSED) expect(parseMinor(text)).toBeNull();
  });

  it('reads a price too big to hold exactly as above any cap', () => {
    expect(parseMinor(TOO_BIG)).toBeGreaterThan(Number.MAX_SAFE_INTEGER);
  });

  it('writes minor units back as input text', () => {
    expect(toPriceInput(TWELVE_FIFTY)).toBe('12.50');
    expect(toPriceInput(CENTS)).toBe('0.07');
    expect(parseMinor(toPriceInput(BIG))).toBe(BIG);
  });

  it('shows two decimals in the language showing', () => {
    i18n.set('en');

    expect(formatMinor(TWELVE_FIFTY, 'USD')).toBe('$12.50');
    expect(formatMinor(BIG, 'USD')).toBe('$1,234.56');
  });

  it('puts the dollar sign before the amount and the others after it', () => {
    i18n.set('en');

    expect(formatMinor(TWELVE_FIFTY, 'RUB')).toBe('12.50\u00A0₽');
    expect(formatMinor(TWELVE_FIFTY, 'AZN')).toBe('12.50\u00A0₼');
    expect(formatMinor(BIG, 'AZN')).toBe('1,234.56\u00A0₼');
    expect(formatMinor(TWELVE_FIFTY, 'KZT')).toBe('12.50\u00A0₸');
  });

  it('labels each currency with its code and sign', () => {
    expect(CURRENCY_LABELS).toEqual({ AZN: 'AZN ₼', KZT: 'KZT ₸', RUB: 'RUB ₽', USD: 'USD $' });
  });

  it('takes a discount off, rounding half up, like the server', () => {
    for (const [price, percent, expected] of DISCOUNTS)
      expect(discountedMinor(price, percent)).toBe(expected);
  });
});
