import { describe, expect, test as it } from 'bun:test';

import { createConfig } from '%/useConfig.svelte.ts';
import { mockFetch } from '../__mocks__/api.ts';

const serverConfig = { server_printing: true, timezone: 'Asia/Baku' };

describe('useConfig', () => {
  it('loads the server config once', async () => {
    const fetchMock = mockFetch(Response.json(serverConfig));
    const config = createConfig();

    await Promise.all([config.load(), config.load()]);
    await config.load();

    expect(config.current).toEqual(serverConfig);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retries after a failed load', async () => {
    const fetchMock = mockFetch(new TypeError('Failed to fetch'), Response.json(serverConfig));
    const config = createConfig();

    await config.load();

    expect(config.current).toBeNull();

    await config.load();

    expect(config.current).toEqual(serverConfig);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
