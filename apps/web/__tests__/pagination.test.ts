// biome-ignore-all lint/style/noMagicNumbers: tables of pages, sizes and counts
import { describe, expect, test as it } from 'bun:test';

import { itemRange, pageCount, parsePage, parseSize } from '%/pagination.ts';

describe('parsePage', () => {
  it('reads a page number from 1', () => {
    expect(parsePage('3')).toBe(3);
  });

  it('falls back to the first page for anything else', () => {
    for (const raw of [null, '', '0', '-2', '1.5', 'x'] as const) expect(parsePage(raw)).toBe(1);
  });
});

describe('parseSize', () => {
  it('accepts only the sizes on offer', () => {
    for (const size of [10, 20, 50, 100]) expect(parseSize(String(size))).toBe(size);
  });

  it('falls back to 20 for any other', () => {
    for (const raw of [null, '', '5', '7', '200', 'x'] as const) expect(parseSize(raw)).toBe(20);
  });
});

describe('pageCount', () => {
  it('rounds up, and an empty list keeps its one page', () => {
    expect(pageCount(0, 10)).toBe(1);
    expect(pageCount(10, 10)).toBe(1);
    expect(pageCount(11, 10)).toBe(2);
  });
});

describe('itemRange', () => {
  it('numbers the items a page holds', () => {
    expect(itemRange(1, 10, 25)).toEqual([1, 10]);
    expect(itemRange(3, 10, 25)).toEqual([21, 25]);
    expect(itemRange(1, 10, 0)).toEqual([0, 0]);
  });
});
