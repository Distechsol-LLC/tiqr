const REVOKE_DELAY = 60_000;
// A field needs quotes when it holds a comma, a quote or a line break
const NEEDS_QUOTES = /[",\r\n]/;

// Quotes are doubled inside a quoted field
const field = (value: string): string =>
  NEEDS_QUOTES.test(value) ? `"${value.replaceAll('"', '""')}"` : value;

// A byte order mark first, so spreadsheets read the letters as UTF-8
const toCsv = (rows: string[][]): string =>
  `\uFEFF${rows.map((row) => row.map(field).join(',')).join('\r\n')}\r\n`;

const downloadCsv = (name: string, csv: string): void => {
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');

  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY);
};

export { downloadCsv, toCsv };
