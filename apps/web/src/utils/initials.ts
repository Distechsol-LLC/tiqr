const WHITESPACE = /\s+/;

// One letter for a one-word name, two for a name of two or more words: the first of each of the first two
export const initialsOf = (name: string, locale: string): string =>
  name
    .trim()
    .split(WHITESPACE)
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase(locale))
    .join('');
