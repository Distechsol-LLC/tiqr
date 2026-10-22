import { i18n } from '%/useLocale.svelte.ts';

const MINOR_PER_UNIT = 100;
const FULL_DISCOUNT = 100;
const MINOR_DIGITS = 2;
// One or two decimals after a point or a comma, as people type them
const PRICE_TEXT = /^(?<whole>\d+)(?:[.,](?<fraction>\d{1,2}))?$/;

// Prices cross the API as whole minor units (cents), so no float ever holds money.
// `text` is what a person typed, such as 12.5, 12,50 or 12; anything else is null.
const parseMinor = (text: string): number | null => {
  const groups = PRICE_TEXT.exec(text.trim())?.groups;

  if (!groups) return null;

  const { fraction = '', whole = '' } = groups;
  const minor = Number(whole) * MINOR_PER_UNIT + Number(fraction.padEnd(MINOR_DIGITS, '0'));

  return Number.isSafeInteger(minor) ? minor : null;
};

// Back into an input's text: 1250 is 12.50
const toPriceInput = (minor: number): string => (minor / MINOR_PER_UNIT).toFixed(MINOR_DIGITS);

// For showing in the language on screen; the server's currency isn't known, so none is added
const formatMinor = (minor: number): string =>
  new Intl.NumberFormat(i18n.code, {
    maximumFractionDigits: MINOR_DIGITS,
    minimumFractionDigits: MINOR_DIGITS,
  }).format(minor / MINOR_PER_UNIT);

// Mirrors `discounted` in apps/core/src/tiqr/core/models.py: rounds half up in minor units
const discountedMinor = (minor: number, percent: number): number =>
  Math.floor((minor * (FULL_DISCOUNT - percent) + FULL_DISCOUNT / 2) / FULL_DISCOUNT);

export { discountedMinor, formatMinor, parseMinor, toPriceInput };
