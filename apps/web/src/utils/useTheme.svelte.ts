type Mode = 'light' | 'dark';

type ThemeController = {
  readonly mode: Mode;
  toggle: () => void;
};

// Also read by the inline script in index.html, which applies the mode before first paint
const STORAGE_KEY = 'tiqr-mode';
const DARK_QUERY = '(prefers-color-scheme: dark)';

const readStored = (): Mode | null => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);

    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
};

// Follows the OS until the user picks a mode, then remembers their pick
const createTheme = (): ThemeController => {
  const media = matchMedia(DARK_QUERY);
  const stored = readStored();
  let isChosen = stored !== null;
  let mode = $state<Mode>(stored ?? (media.matches ? 'dark' : 'light'));

  const apply = (next: Mode): void => {
    mode = next;
    document.documentElement.dataset.mode = next;
  };

  apply(mode);

  media.addEventListener('change', (event) => {
    if (!isChosen) apply(event.matches ? 'dark' : 'light');
  });

  return {
    get mode(): Mode {
      return mode;
    },
    toggle: (): void => {
      const next = mode === 'dark' ? 'light' : 'dark';

      isChosen = true;
      apply(next);

      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Storage can be blocked; the pick still holds for this visit
      }
    },
  };
};

const theme = createTheme();

export { theme };
