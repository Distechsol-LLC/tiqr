type Cell = string | number;
type Sheet = { name: string; rows: Cell[][] };

const REVOKE_DELAY = 60_000;
const MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const ENCODER = new TextEncoder();
const XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
const SPREADSHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const RELATIONSHIPS_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const PACKAGE_RELATIONSHIPS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships';
// Excel rejects longer names, and these characters, in a sheet name
const SHEET_NAME_MAX = 31;
const SHEET_NAME_FORBIDDEN = /[:\\/?*[\]]/g;
const SHEET_NAME_EDGE = /^['\s]+|['\s]+$/g;
// XML can't carry control characters, but keeps tab, line feed and carriage return
const SPACE = 0x20;
const TAB = 0x09;
const LINE_FEED = 0x0a;
const CARRIAGE_RETURN = 0x0d;
const CAPITAL_A = 65;
const LETTERS = 26;
// Every column has the same static width, so long names are cut short rather than widening it
const COLUMN_WIDTH = 18;

// Zip records are laid out as little-endian fields of these byte widths
const U16 = 2;
const U32 = 4;
const BYTE = 256;
const BYTE_MASK = BYTE - 1;
const BYTE_BITS = 8;
const CRC_MASK = 0xffffffff;
const CRC_POLYNOMIAL = 0xedb88320;
const LOCAL_SIGNATURE = 0x04034b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const END_SIGNATURE = 0x06054b50;
const ZIP_VERSION = 20;
// Bit 11 marks the names as UTF-8
const UTF8_NAMES = 0x0800;
// The zip date for 1 January 1980, the earliest it can hold; the time stays at midnight
const ZIP_DATE = 0x21;

const CRC_TABLE = Array.from({ length: BYTE }, (_, index) => {
  let value = index;

  for (let bit = 0; bit < BYTE_BITS; bit += 1) {
    value = value & 1 ? CRC_POLYNOMIAL ^ (value >>> 1) : value >>> 1;
  }

  return value >>> 0;
});

const crc32 = (bytes: Uint8Array): number => {
  let crc = CRC_MASK;

  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & BYTE_MASK] ^ (crc >>> BYTE_BITS);

  return (crc ^ CRC_MASK) >>> 0;
};

// Each field is a value and its width in bytes, written least significant byte first
const record = (...fields: [number, number][]): Uint8Array =>
  Uint8Array.from(
    fields.flatMap(([value, width]) =>
      Array.from({ length: width }, (_, index) => Math.floor(value / BYTE ** index) % BYTE)
    )
  );

const concat = (chunks: Uint8Array[]): Uint8Array<ArrayBuffer> => {
  const out = new Uint8Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0));
  let offset = 0;

  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }

  return out;
};

// Stored rather than compressed: the parts are small, and the container stays simple
const zip = (files: [string, string][]): Uint8Array<ArrayBuffer> => {
  const entries = files.map(([path, text]) => {
    const data = ENCODER.encode(text);

    return { crc: crc32(data), data, name: ENCODER.encode(path) };
  });
  const locals: Uint8Array[] = [];
  const offsets: number[] = [];
  let size = 0;

  for (const { crc, data, name } of entries) {
    const header = record(
      [LOCAL_SIGNATURE, U32],
      [ZIP_VERSION, U16],
      [UTF8_NAMES, U16],
      [0, U16],
      [0, U16],
      [ZIP_DATE, U16],
      [crc, U32],
      [data.length, U32],
      [data.length, U32],
      [name.length, U16],
      [0, U16]
    );

    offsets.push(size);
    locals.push(header, name, data);
    size += header.length + name.length + data.length;
  }

  const directory = entries.flatMap(({ crc, data, name }, index) => [
    record(
      [CENTRAL_SIGNATURE, U32],
      [ZIP_VERSION, U16],
      [ZIP_VERSION, U16],
      [UTF8_NAMES, U16],
      [0, U16],
      [0, U16],
      [ZIP_DATE, U16],
      [crc, U32],
      [data.length, U32],
      [data.length, U32],
      [name.length, U16],
      [0, U16],
      [0, U16],
      [0, U16],
      [0, U16],
      [0, U32],
      [offsets[index] ?? 0, U32]
    ),
    name,
  ]);
  const directorySize = directory.reduce((sum, chunk) => sum + chunk.length, 0);
  const end = record(
    [END_SIGNATURE, U32],
    [0, U16],
    [0, U16],
    [entries.length, U16],
    [entries.length, U16],
    [directorySize, U32],
    [size, U32],
    [0, U16]
  );

  return concat([...locals, ...directory, end]);
};

const isXmlCharacter = (code: number): boolean =>
  code >= SPACE || code === TAB || code === LINE_FEED || code === CARRIAGE_RETURN;

const escapeXml = (text: string): string =>
  Array.from(text)
    .filter((char) => isXmlCharacter(char.codePointAt(0) ?? 0))
    .join('')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');

// A is the first column, Z the 26th and AA the 27th
const columnName = (index: number): string => {
  let name = '';

  for (let number = index + 1; number > 0; number = Math.floor((number - 1) / LETTERS)) {
    name = String.fromCharCode(CAPITAL_A + ((number - 1) % LETTERS)) + name;
  }

  return name;
};

const cellXml = (value: Cell, reference: string): string =>
  typeof value === 'number'
    ? `<c r="${reference}"><v>${value}</v></c>`
    : `<c r="${reference}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;

const sheetXml = (rows: Cell[][]): string => {
  const width = Math.max(...rows.map((row) => row.length));
  const body = rows
    .map(
      (row, rowIndex) =>
        `<row r="${rowIndex + 1}">${row
          .map((value, columnIndex) => cellXml(value, `${columnName(columnIndex)}${rowIndex + 1}`))
          .join('')}</row>`
    )
    .join('');

  return `${XML_HEADER}<worksheet xmlns="${SPREADSHEET_NS}"><cols><col min="1" max="${width}" width="${COLUMN_WIDTH}" customWidth="1"/></cols><sheetData>${body}</sheetData></worksheet>`;
};

// Names Excel can't take are cut back, and a name already used gets a number after it
const sheetNames = (names: string[]): string[] => {
  const taken = new Set<string>();

  return names.map((name) => {
    const base =
      name
        .replace(SHEET_NAME_FORBIDDEN, ' ')
        .slice(0, SHEET_NAME_MAX)
        .replace(SHEET_NAME_EDGE, '') || 'Sheet';
    let unique = base;

    for (let number = 2; taken.has(unique.toLowerCase()); number += 1) {
      const suffix = ` (${number})`;

      unique = `${base.slice(0, SHEET_NAME_MAX - suffix.length)}${suffix}`;
    }

    taken.add(unique.toLowerCase());

    return unique;
  });
};

const workbookXml = (names: string[]): string => {
  const sheets = names
    .map(
      (name, index) =>
        `<sheet name="${escapeXml(name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`
    )
    .join('');

  return `${XML_HEADER}<workbook xmlns="${SPREADSHEET_NS}" xmlns:r="${RELATIONSHIPS_NS}"><sheets>${sheets}</sheets></workbook>`;
};

const workbookRelationshipsXml = (sheetCount: number): string => {
  const sheets = Array.from(
    { length: sheetCount },
    (_, index) =>
      `<Relationship Id="rId${index + 1}" Type="${RELATIONSHIPS_NS}/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`
  ).join('');

  return `${XML_HEADER}<Relationships xmlns="${PACKAGE_RELATIONSHIPS_NS}">${sheets}<Relationship Id="rId${sheetCount + 1}" Type="${RELATIONSHIPS_NS}/styles" Target="styles.xml"/></Relationships>`;
};

const contentTypesXml = (sheetCount: number): string => {
  const sheets = Array.from(
    { length: sheetCount },
    (_, index) =>
      `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`
  ).join('');

  return `${XML_HEADER}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets}</Types>`;
};

const ROOT_RELATIONSHIPS = `${XML_HEADER}<Relationships xmlns="${PACKAGE_RELATIONSHIPS_NS}"><Relationship Id="rId1" Type="${RELATIONSHIPS_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>`;

// The one plain style every cell uses
const STYLES = `${XML_HEADER}<styleSheet xmlns="${SPREADSHEET_NS}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>`;

// One sheet per entry, in order; the first sheet is the one the workbook opens on
const toXlsx = (sheets: Sheet[]): Uint8Array<ArrayBuffer> => {
  const names = sheetNames(sheets.map(({ name }) => name));

  return zip([
    ['[Content_Types].xml', contentTypesXml(sheets.length)],
    ['_rels/.rels', ROOT_RELATIONSHIPS],
    ['xl/workbook.xml', workbookXml(names)],
    ['xl/_rels/workbook.xml.rels', workbookRelationshipsXml(sheets.length)],
    ['xl/styles.xml', STYLES],
    ...sheets.map(({ rows }, index): [string, string] => [
      `xl/worksheets/sheet${index + 1}.xml`,
      sheetXml(rows),
    ]),
  ]);
};

const downloadXlsx = (name: string, workbook: Uint8Array<ArrayBuffer>): void => {
  const url = URL.createObjectURL(new Blob([workbook], { type: MIME }));
  const link = document.createElement('a');

  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY);
};

export type { Sheet };
export { downloadXlsx, toXlsx };
