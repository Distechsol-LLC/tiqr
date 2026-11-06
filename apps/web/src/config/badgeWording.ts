import type { Messages } from '@/locales/en.ts';

type Reword = (text: string) => string;
type Parts = { ending?: string; initial: string };

// The named groups of a replacer's match, which String.replace passes last
const partsOf = (match: unknown[]): Parts => match.at(-1) as Parts;

// Each language's word for a ticket, swapped for its word for a badge with the ending each form
// takes. Only whole words change, so "ticketing" or "билетный" stay as they are.
const EN_TICKET = /\b(?<initial>[Tt])icket(?<ending>s?)\b/g;

// Билет and бейдж are both masculine, so only the endings that differ need changing
const RU_TICKET =
  /(?<![а-яёА-ЯЁ])(?<initial>[Бб])илет(?<ending>ами|ам|ах|ов|ом|а|е|у|ы)?(?![а-яёА-ЯЁ])/g;
const RU_ENDINGS: Record<string, string> = {
  а: 'а',
  ам: 'ам',
  ами: 'ами',
  ах: 'ах',
  е: 'е',
  ов: 'ей',
  ом: 'ем',
  у: 'у',
  ы: 'и',
};

// Kazakh suffixes voice after бейдж's final ж: билеттер is бейдждер, билетке is бейджге
const KK_TICKET = /(?<!\p{L})(?<initial>[Бб])илет(?<ending>\p{L}*)/gu;
const KK_VOICELESS = /^[кт]/;
const KK_VOICED: Record<string, string> = { к: 'г', т: 'д' };

// Vəsiqə ends in a vowel, so a case ending that starts with one takes a buffer letter:
// biletin is vəsiqənin, biletə is vəsiqəyə. Both words' last vowels harmonize the same way
const AZ_TICKET = /(?<!\p{L})(?<initial>[Bb])ilet(?<ending>\p{L}*)/gu;
const AZ_BUFFERS: Record<string, string> = { i: 'n', ə: 'y' };

const REWORDS: Record<'az' | 'en' | 'kk' | 'ru', Reword> = {
  az: (text) =>
    text.replace(AZ_TICKET, (...match: unknown[]) => {
      const { ending = '', initial } = partsOf(match);

      return `${initial === 'B' ? 'V' : 'v'}əsiqə${AZ_BUFFERS[ending.charAt(0)] ?? ''}${ending}`;
    }),
  en: (text) =>
    text.replace(EN_TICKET, (...match: unknown[]) => {
      const { ending = '', initial } = partsOf(match);

      return `${initial === 'T' ? 'B' : 'b'}adge${ending}`;
    }),
  kk: (text) =>
    text.replace(KK_TICKET, (...match: unknown[]) => {
      const { ending = '', initial } = partsOf(match);

      return `${initial}ейдж${ending.replace(KK_VOICELESS, (sound) => KK_VOICED[sound] ?? sound)}`;
    }),
  ru: (text) =>
    text.replace(RU_TICKET, (...match: unknown[]) => {
      const { ending = '', initial } = partsOf(match);

      return `${initial}ейдж${RU_ENDINGS[ending] ?? ''}`;
    }),
};

// Stand-ins for a message function's text arguments, from Unicode's private use area, so names
// and serials put into a message keep their own wording
const HOLE = /(?<index>\d+)/g;

const rewordFunction =
  (message: (...args: never[]) => unknown, reword: Reword) =>
  (...args: unknown[]): unknown => {
    const held: string[] = [];
    const masked = args.map((arg) => {
      if (typeof arg !== 'string') return arg;

      held.push(arg);

      return `${held.length - 1}`;
    });
    const text = (message as (...values: unknown[]) => unknown)(...masked);

    return typeof text === 'string'
      ? reword(text).replace(HOLE, (_, index: string) => held[Number(index)] ?? '')
      : text;
  };

const rewordAll = (value: unknown, reword: Reword): unknown => {
  if (typeof value === 'string') return reword(value);
  if (typeof value === 'function')
    return rewordFunction(value as (...args: never[]) => unknown, reword);
  if (value !== null && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, rewordAll(entry, reword)])
    );

  return value;
};

// The settings page names both modes, so its tickets stay tickets whichever mode is on
const KEPT: ReadonlySet<string> = new Set<keyof Messages>(['settings']);

const cache = new Map<string, Messages>();

// The same messages with every ticket made a badge, built once per language
const toBadgeWording = (code: keyof typeof REWORDS, messages: Messages): Messages => {
  let worded = cache.get(code);

  if (!worded) {
    worded = Object.fromEntries(
      Object.entries(messages).map(([key, section]) => [
        key,
        KEPT.has(key) ? section : rewordAll(section, REWORDS[code]),
      ])
    ) as Messages;
    cache.set(code, worded);
  }

  return worded;
};

export { toBadgeWording };
