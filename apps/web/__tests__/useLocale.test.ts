import { afterEach, describe, expect, test as it } from 'bun:test';

import { DEFAULT_LOCALE, LOCALES, LOCALE_CODES } from '@/config/locales.ts';
import { createLocale } from '%/useLocale.svelte.ts';

const STORAGE_KEY = 'tiqr-locale';

// Bun has neither localStorage nor navigator.languages, so each test lends its own
const useStorage = (entries: Record<string, string> = {}): Map<string, string> => {
  const store = new Map(Object.entries(entries));

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string): string | null => store.get(key) ?? null,
      setItem: (key: string, value: string): void => {
        store.set(key, value);
      },
    },
  });

  return store;
};

const useLanguages = (languages: string[]): void => {
  Object.defineProperty(navigator, 'languages', { configurable: true, value: languages });
};

// Walks a message tree into its leaves, each a dotted path and the text or function found there
const leaves = (tree: object, prefix = ''): [string, unknown][] =>
  Object.entries(tree).flatMap(([key, value]: [string, unknown]) =>
    value && typeof value === 'object'
      ? leaves(value, `${prefix}${key}.`)
      : [[`${prefix}${key}`, value] as [string, unknown]]
  );

const shape = (tree: object): [string, string][] =>
  leaves(tree)
    .map(([path, value]): [string, string] => [path, typeof value])
    .toSorted(([a], [b]) => a.localeCompare(b));

describe('useLocale', () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage');
    Reflect.deleteProperty(navigator, 'languages');
  });

  it('falls back to the default without storage or browser languages', () => {
    expect(createLocale().code).toBe(DEFAULT_LOCALE);
  });

  it('follows the first browser language it has', () => {
    useLanguages(['de-DE', 'az-Latn-AZ', 'ru']);

    const locale = createLocale();

    expect(locale.code).toBe('az');
    expect(locale.t).toBe(LOCALES.az.messages);
  });

  it('shows the browser language over the first one the server offers', () => {
    useLanguages(['ru-RU']);

    const locale = createLocale();

    locale.configure(['az', 'en', 'ru']);

    expect(locale.code).toBe('ru');
  });

  it('prefers the stored pick over the browser', () => {
    useStorage({ [STORAGE_KEY]: 'ru' });
    useLanguages(['az']);

    expect(createLocale().code).toBe('ru');
  });

  it('ignores a stored value it has no language for', () => {
    useStorage({ [STORAGE_KEY]: 'xx' });
    useLanguages(['ru-RU']);

    expect(createLocale().code).toBe('ru');
  });

  it('switches the messages and remembers the pick', () => {
    const store = useStorage();
    const locale = createLocale();

    locale.set('ru');

    expect(locale.code).toBe('ru');
    expect(locale.t.nav.tickets).toBe(LOCALES.ru.messages.nav.tickets);
    expect(store.get(STORAGE_KEY)).toBe('ru');
  });

  it('keeps the pick for the visit when storage is blocked', () => {
    const locale = createLocale();

    locale.set('az');

    expect(locale.code).toBe('az');
  });

  it('lists the default language first', () => {
    expect(LOCALE_CODES[0]).toBe(DEFAULT_LOCALE);
    expect(new Set<string>(LOCALE_CODES)).toEqual(new Set(Object.keys(LOCALES)));
    expect(LOCALE_CODES).toHaveLength(Object.keys(LOCALES).length);
  });

  it.each(LOCALE_CODES)('fills every message in %s', (code) => {
    const { messages } = LOCALES[code];

    expect(shape(messages)).toEqual(shape(LOCALES[DEFAULT_LOCALE].messages));
    expect(leaves(messages).filter(([, value]) => value === '')).toEqual([]);
  });
});
