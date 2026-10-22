import { describe, expect, test as it } from 'bun:test';

import { initialsOf } from '%/initials.ts';

describe('initialsOf', () => {
  it('takes one letter for one word', () => {
    expect(initialsOf('ada', 'en')).toBe('A');
  });

  it('takes the first letter of the first two words', () => {
    expect(initialsOf('ada lovelace', 'en')).toBe('AL');
    expect(initialsOf('  ada   king  lovelace ', 'en')).toBe('AK');
  });

  it('is empty for an empty name', () => {
    expect(initialsOf('', 'en')).toBe('');
  });
});
