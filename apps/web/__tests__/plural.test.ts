import { describe, expect, test as it } from 'bun:test';

import { plural } from '%/plural.ts';

const ONE = 1;
const TWO = 2;
const FIVE = 5;
const ELEVEN = 11;
const TWENTY_TWO = 22;
const TWENTY_ONE = 21;
const HUNDRED = 100;

describe('plural', () => {
  it('picks the English one form only for exactly one', () => {
    const forms = { one: 'bilet', other: 'biletlər' };

    expect(plural('en', 1, forms)).toBe('bilet');
    expect(plural('en', 0, forms)).toBe('biletlər');
    expect(plural('en', 2, forms)).toBe('biletlər');
  });

  it('follows Russian one, few and many rules, including the 21 and 22 cases', () => {
    const forms = { few: 'few', many: 'many', one: 'one', other: 'other' };

    expect(plural('ru', 1, forms)).toBe('one');
    expect(plural('ru', TWENTY_ONE, forms)).toBe('one');
    expect(plural('ru', TWO, forms)).toBe('few');
    expect(plural('ru', TWENTY_TWO, forms)).toBe('few');
    expect(plural('ru', FIVE, forms)).toBe('many');
    expect(plural('ru', ELEVEN, forms)).toBe('many');
  });

  it('falls back to the other form when the locale has no form for the count', () => {
    expect(plural('ru', TWO, { other: 'fallback' })).toBe('fallback');
  });

  it('gives Azerbaijani the same form for every count, since its nouns stay singular', () => {
    const forms = { other: 'bilet' };

    for (const count of [0, ONE, TWO, FIVE, ELEVEN, HUNDRED]) {
      expect(plural('az', count, forms)).toBe('bilet');
    }
  });
});
