import { DEFAULT_LOCALE, LOCALE_CODES, type Locale, isLocale } from '@/config/locales.ts';
import { fetchBranding } from '%/api.ts';
import type { Branding } from '$/branding.ts';
import { type Currency, currencySchema } from '$/catalog.ts';

const APP_NAME = 'TiQR';
const THEME_DEFAULT = 'default';
const LOGO_URL = '/api/logo';

type BrandingController = {
  readonly appName: string;
  // Every currency until the server says which its languages use
  readonly currencies: readonly Currency[];
  readonly fallbackLocale: Locale;
  // The built-in logo is used when the install has none of its own
  readonly logoSrc: string | null;
  // The languages offered, as the web app's own codes: en-US is en
  readonly locales: readonly Locale[];
  readonly theme: string;
  load: () => Promise<void>;
};

// The primary subtag, as long as the app has that language; each language is listed once
const toLocales = (languages: readonly string[]): Locale[] => [
  ...new Set(languages.map((tag) => tag.split('-')[0]?.toLowerCase() ?? '').filter(isLocale)),
];

// Server settings don't change while it runs, so one load is kept for the visit. Without an answer
// the app looks as it ships, so a failed load never blocks sign-in.
const createBranding = (): BrandingController => {
  let current = $state<Branding | null>(null);

  const offered = (): Locale[] => toLocales(current?.languages ?? []);

  return {
    get appName(): string {
      return current?.app_name || APP_NAME;
    },
    get currencies(): readonly Currency[] {
      return current && current.currencies.length > 0 ? current.currencies : currencySchema.options;
    },
    get fallbackLocale(): Locale {
      const [first = DEFAULT_LOCALE] = offered();
      const [preferred] = toLocales([current?.default_language ?? '']);

      return preferred && offered().includes(preferred) ? preferred : first;
    },
    load: async (): Promise<void> => {
      const result = await fetchBranding();

      if (result.ok) current = result.data;
    },
    get locales(): readonly Locale[] {
      const locales = offered();

      return locales.length > 0 ? locales : LOCALE_CODES;
    },
    get logoSrc(): string | null {
      return current?.has_logo ? LOGO_URL : null;
    },
    get theme(): string {
      return current?.theme || THEME_DEFAULT;
    },
  };
};

const branding = createBranding();

export { branding, createBranding };
