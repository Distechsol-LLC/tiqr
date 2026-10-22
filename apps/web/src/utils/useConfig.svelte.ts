import { fetchConfig } from '%/api.ts';
import type { Config } from '$/operations.ts';

type ConfigController = {
  readonly current: Config | null;
  load: () => Promise<void>;
};

// Server settings don't change while it runs, so one successful load is kept for the visit
const createConfig = (): ConfigController => {
  let current = $state<Config | null>(null);
  let loading: Promise<void> | null = null;

  return {
    get current(): Config | null {
      return current;
    },
    load: (): Promise<void> => {
      loading ??= fetchConfig().then((result) => {
        if (result.ok) current = result.data;
        // A failed load can be retried by the next page that needs it
        else loading = null;
      });

      return loading;
    },
  };
};

const config = createConfig();

export { config, createConfig };
