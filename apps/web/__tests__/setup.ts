import { afterEach, mock } from 'bun:test';
import { Transpiler, plugin } from 'bun';

import { compileModule } from 'svelte/compiler';

const RUNES_MODULE = /\.svelte\.ts$/;

// Bun can't run runes, so .svelte.ts modules go through the Svelte compiler first
plugin({
  name: 'svelte-runes',
  setup: (build) => {
    const transpiler = new Transpiler({ loader: 'ts' });

    build.onLoad({ filter: RUNES_MODULE }, async ({ path }) => {
      const source = transpiler.transformSync(await Bun.file(path).text());
      const { js } = compileModule(source, { filename: path, generate: 'client' });

      return { contents: js.code, loader: 'js' };
    });
  },
});

// Undo every spy so each test starts with the real fetch
afterEach(() => {
  mock.restore();
});
