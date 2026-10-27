import { describe, expect, test as it } from 'bun:test';

import { activateLicense, fetchRequestCode, fetchSession } from '%/api.ts';
import { createLicense, license } from '%/useLicense.svelte.ts';
import type { LicenseStatus } from '$/license.ts';
import { mockFetch } from '../__mocks__/api.ts';

const MACHINE_ID_LENGTH = 32;

const status: LicenseStatus = {
  days_remaining: 30,
  expires_at: '2030-07-01T00:00:00+00:00',
  is_valid: true,
  licensed_to: 'Acme',
  machine_id: 'A'.repeat(MACHINE_ID_LENGTH),
  state: 'active',
  type: 'standard',
};

describe('useLicense', () => {
  it('starts unknown, which the app treats as blocked', () => {
    const controller = createLicense();

    expect(controller.status).toBeNull();
    expect(controller.failed).toBe(false);
  });

  it('keeps a verified status', async () => {
    mockFetch(Response.json(status));

    const controller = createLicense();

    await controller.refresh();

    expect(controller.status).toEqual(status);
    expect(controller.failed).toBe(false);
  });

  it('marks a failed check as failed, then recovers', async () => {
    mockFetch(new TypeError('Failed to fetch'), Response.json(status));

    const controller = createLicense();

    await controller.refresh();

    expect(controller.status).toBeNull();
    expect(controller.failed).toBe(true);

    await controller.refresh();

    expect(controller.failed).toBe(false);
    expect(controller.status?.state).toBe('active');
  });

  it('treats a malformed status as a failure', async () => {
    mockFetch(Response.json({ state: 'active' }));

    const controller = createLicense();

    await controller.refresh();

    expect(controller.status).toBeNull();
    expect(controller.failed).toBe(true);
  });

  it('re-checks when the server refuses a request for want of a license', async () => {
    const fetchMock = mockFetch(
      Response.json({ code: 'license_required', detail: 'No license' }, { status: 403 }),
      Response.json({ ...status, is_valid: false, state: 'expired' })
    );

    await fetchSession();
    // The listener's refresh runs on the next turn
    await Bun.sleep(0);
    await Bun.sleep(0);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(license.status?.state).toBe('expired');
  });
});

describe('license api', () => {
  it('asks for a request code', async () => {
    const fetchMock = mockFetch(Response.json({ code: 'abc' }));

    expect(await fetchRequestCode()).toEqual({ data: 'abc', ok: true });
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/license/request-code');
  });

  it('posts the key with the CSRF token', async () => {
    const fetchMock = mockFetch(Response.json(status));

    await activateLicense('csrf', 'a.b');

    const [url, init] = fetchMock.mock.calls[0] ?? [];

    expect(url).toBe('/api/license/activate');
    expect(init?.body).toBe(JSON.stringify({ license_key: 'a.b' }));
  });

  it('surfaces the server code of a refused key', async () => {
    mockFetch(
      Response.json({ code: 'license_wrong_machine', detail: 'Other machine' }, { status: 400 })
    );

    expect(await activateLicense('csrf', 'a.b')).toEqual({
      error: {
        code: 'license_wrong_machine',
        detail: 'Other machine',
        kind: 'server',
        status: 400,
      },
      ok: false,
    });
  });
});
