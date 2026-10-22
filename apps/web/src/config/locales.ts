import { az } from '@/locales/az.ts';
import { type Messages, en } from '@/locales/en.ts';
import { ru } from '@/locales/ru.ts';

type LocaleEntry = {
  // The language's own name, so people find it whichever language is showing
  label: string;
  messages: Messages;
};

// Adding a language: translate locales/en.ts into a new file there and list it here
const LOCALES = {
  az: { label: 'Azərbaycanca', messages: az },
  en: { label: 'English', messages: en },
  ru: { label: 'Русский', messages: ru },
} satisfies Record<string, LocaleEntry>;

type Locale = keyof typeof LOCALES;

const DEFAULT_LOCALE: Locale = 'en';

// Menu order, kept apart from LOCALES because the linter keeps that object's keys alphabetical
const LOCALE_CODES: Locale[] = ['en', 'ru', 'az'];

const isLocale = (value: string): value is Locale => Object.hasOwn(LOCALES, value);

export type { Locale };
export { DEFAULT_LOCALE, LOCALES, LOCALE_CODES, isLocale };
