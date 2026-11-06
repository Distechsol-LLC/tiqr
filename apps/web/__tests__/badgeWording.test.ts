import { afterEach, describe, expect, test as it } from 'bun:test';

import { toBadgeWording } from '@/config/badgeWording.ts';
import { az } from '@/locales/az.ts';
import { type Messages, en } from '@/locales/en.ts';
import { kk } from '@/locales/kk.ts';
import { ru } from '@/locales/ru.ts';
import { i18n } from '%/useLocale.svelte.ts';
import { mode } from '%/useMode.svelte.ts';

const CYRILLIC_TICKET = /[Бб]илет/;
const LATIN_TICKET = /[Bb]ilet/;

// Every message but the settings page's, which names both modes on purpose
const textOf = (messages: Messages): string => {
  const { settings: _, ...rest } = messages;

  return JSON.stringify(rest);
};

describe('badge wording', () => {
  afterEach(() => {
    mode.set('ticket');
    i18n.set('en');
  });

  it('makes every ticket a badge in English', () => {
    const worded = toBadgeWording('en', en);

    expect(worded.nav.tickets).toBe('Badges');
    expect(worded.tickets.new).toBe('New Badge');
    expect(worded.ticketForm.title).toBe('New badge');
    expect(worded.tickets.emptySearch).toBe('No badges match the search');
  });

  it('keeps the endings each Russian case takes', () => {
    const worded = toBadgeWording('ru', ru);

    expect(worded.nav.tickets).toBe('Бейджи');
    expect(worded.tickets.title).toBe('Бейджи');
    expect(worded.ticketForm.created).toBe('Бейдж создан');
    expect(textOf(worded)).not.toMatch(CYRILLIC_TICKET);
  });

  it('voices Kazakh suffixes after the final ж', () => {
    const worded = toBadgeWording('kk', kk);

    expect(worded.nav.tickets).toBe('Бейдждер');
    expect(textOf(worded)).not.toMatch(CYRILLIC_TICKET);
  });

  it('adds the buffer letter Azerbaijani endings need after a vowel', () => {
    const worded = toBadgeWording('az', az);

    expect(worded.nav.tickets).toBe('Vəsiqələr');
    expect(worded.errors.validFromRequired).toBe('Vəsiqənin başlama vaxtını seçin.');
    expect(textOf(worded)).not.toMatch(LATIN_TICKET);
  });

  it('rewords message functions but never the names put into them', () => {
    const worded = toBadgeWording('en', en);

    expect(worded.tickets.revokeConfirm('Ticket office')).toBe(
      'Revoke Ticket office? It stops granting access.'
    );
    expect(worded.overview.cleanup.done(2)).toBe('2 finished badges removed from BioStar.');
  });

  it('leaves the settings page, which names both modes, as it is', () => {
    expect(toBadgeWording('en', en).settings).toBe(en.settings);
  });

  it('follows the mode as it switches', () => {
    expect(i18n.t.nav.tickets).toBe('Tickets');
    mode.set('badge');
    expect(i18n.t.nav.tickets).toBe('Badges');
    i18n.set('ru');
    expect(i18n.t.nav.tickets).toBe('Бейджи');
  });
});
