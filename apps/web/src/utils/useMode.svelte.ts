import type { Mode } from '$/settings.ts';

type ModeController = {
  readonly current: Mode;
  // Badges name their visitor and carry no price; tickets name no one and may admit a group
  readonly isBadge: boolean;
  set: (next: Mode) => void;
};

// The server's mode, from the branding it sends at load and from a switch on the settings page.
// Text, forms and tables read it, so all of them follow a switch without a reload.
const createMode = (): ModeController => {
  let current = $state<Mode>('ticket');

  return {
    get current(): Mode {
      return current;
    },
    get isBadge(): boolean {
      return current === 'badge';
    },
    set: (next: Mode): void => {
      current = next;
    },
  };
};

const mode = createMode();

export { mode };
