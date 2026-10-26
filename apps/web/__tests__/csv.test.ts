import { describe, expect, test as it } from 'bun:test';

import { toCsv } from '%/csv.ts';

describe('toCsv', () => {
  it('writes rows of plain fields, CRLF-ended, after a byte order mark', () => {
    expect(
      toCsv([
        ['Metric', 'Count'],
        ['Total', '3'],
      ])
    ).toBe('\uFEFFMetric,Count\r\nTotal,3\r\n');
  });

  it('quotes a field with a comma, a quote or a line break, doubling its quotes', () => {
    expect(toCsv([['a,b', 'say "hi"', 'one\ntwo']])).toBe(
      '\uFEFF"a,b","say ""hi""","one\ntwo"\r\n'
    );
  });

  it('keeps letters outside ASCII as they are', () => {
    expect(toCsv([['Bütün dövr', 'Қазақша']])).toBe('\uFEFFBütün dövr,Қазақша\r\n');
  });
});
