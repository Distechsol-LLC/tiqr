import { DEFAULT_LOCALE, LOCALES, LOCALE_CODES, type Locale, isLocale } from '@/config/locales.ts';
import type { Messages } from '@/locales/en.ts';

type LocaleController = {
  readonly code: Locale;
  readonly t: Messages;
  set: (next: Locale) => void;
  // Narrows the choice to the languages the server offers. A stored or browser pick outside them
  // gives way to the first language offered.
  configure: (offered: readonly Locale[]) => void;
};

// Also read by the inline script in index.html, which sets <html lang> before first paint
const STORAGE_KEY = 'tiqr-locale';

const readStored = (offered: readonly Locale[] = LOCALE_CODES): Locale | null => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);

    return stored !== null && isLocale(stored) && offered.includes(stored) ? stored : null;
  } catch {
    return null;
  }
};

// The browser's first language we have, by its primary subtag: az-Latn-AZ reads as az
const readPreferred = (offered: readonly Locale[] = LOCALE_CODES): Locale | null =>
  (navigator.languages ?? [])
    .map((tag) => tag.split('-')[0]?.toLowerCase() ?? '')
    .find((tag): tag is Locale => isLocale(tag) && offered.includes(tag)) ?? null;

// Follows the browser until the user picks a language, then remembers their pick.
// Reading `t` inside a component, $derived or zod message tracks the language, so text follows it.
const createLocale = (): LocaleController => {
  let code = $state<Locale>(readStored() ?? readPreferred() ?? DEFAULT_LOCALE);

  return {
    get code(): Locale {
      return code;
    },
    configure: (offered: readonly Locale[]): void => {
      code = readStored(offered) ?? readPreferred(offered) ?? offered[0] ?? DEFAULT_LOCALE;
    },
    set: (next: Locale): void => {
      code = next;

      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Storage can be blocked; the pick still holds for this visit
      }
    },
    get t(): Messages {
      return LOCALES[code].messages;
    },
  };
};

const i18n = createLocale();

export { createLocale, i18n };
