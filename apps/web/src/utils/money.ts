import { i18n } from '%/useLocale.svelte.ts';
import type { Currency } from '$/catalog.ts';

const MINOR_PER_UNIT = 100;
const FULL_DISCOUNT = 100;
const MINOR_DIGITS = 2;
// One or two decimals after a point or a comma, as people type them
const PRICE_TEXT = /^(?<whole>\d+)(?:[.,](?<fraction>\d{1,2}))?$/;

// Prices cross the API as whole minor units (cents), so no float ever holds money.
// `text` is what a person typed, such as 12.5, 12,50 or 12; anything else is null.
// Too long to be exact is still a number, far above any cap, so callers compare it to their limit.
const parseMinor = (text: string): number | null => {
  const groups = PRICE_TEXT.exec(text.trim())?.groups;

  if (!groups) return null;

  const { fraction = '', whole = '' } = groups;
  const minor = Number(whole) * MINOR_PER_UNIT + Number(fraction.padEnd(MINOR_DIGITS, '0'));

  return minor;
};

// Back into an input's text: 1250 is 12.50
const toPriceInput = (minor: number): string => (minor / MINOR_PER_UNIT).toFixed(MINOR_DIGITS);

// The sign of each currency, and whether it goes before the amount: dollars do, roubles, manats
// and tenge come after it
const CURRENCY_MARKS: Record<Currency, { before: boolean; mark: string }> = {
  AZN: { before: false, mark: '₼' },
  KZT: { before: false, mark: '₸' },
  RUB: { before: false, mark: '₽' },
  USD: { before: true, mark: '$' },
};

// Code and sign together, as the currency is picked
const CURRENCY_LABELS: Record<Currency, string> = {
  AZN: `AZN ${CURRENCY_MARKS.AZN.mark}`,
  KZT: `KZT ${CURRENCY_MARKS.KZT.mark}`,
  RUB: `RUB ${CURRENCY_MARKS.RUB.mark}`,
  USD: `USD ${CURRENCY_MARKS.USD.mark}`,
};

// For showing in the language on screen. A no-break space keeps a trailing sign off its amount.
const formatMinor = (minor: number, currency: Currency): string => {
  const amount = new Intl.NumberFormat(i18n.code, {
    maximumFractionDigits: MINOR_DIGITS,
    minimumFractionDigits: MINOR_DIGITS,
  }).format(minor / MINOR_PER_UNIT);
  const { before, mark } = CURRENCY_MARKS[currency];

  return before ? `${mark}${amount}` : `${amount}\u00A0${mark}`;
};

// Mirrors `discounted` in apps/core/src/tiqr/core/models.py: rounds half up in minor units
const discountedMinor = (minor: number, percent: number): number =>
  Math.floor((minor * (FULL_DISCOUNT - percent) + FULL_DISCOUNT / 2) / FULL_DISCOUNT);

export { CURRENCY_LABELS, discountedMinor, formatMinor, parseMinor, toPriceInput };
