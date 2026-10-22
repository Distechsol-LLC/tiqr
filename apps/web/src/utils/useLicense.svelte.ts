import { type ApiResult, fetchLicense, listenForLicense } from '%/api.ts';
import type { LicenseStatus } from '$/license.ts';

type LicenseController = {
  // Unknown is blocked: the app shows only after a check that says it is valid
  readonly failed: boolean;
  readonly status: LicenseStatus | null;
  refresh: () => Promise<ApiResult<LicenseStatus>>;
};

const createLicense = (): LicenseController => {
  let status = $state<LicenseStatus | null>(null);
  let failed = $state(false);

  return {
    get failed(): boolean {
      return failed;
    },
    refresh: async (): Promise<ApiResult<LicenseStatus>> => {
      const result = await fetchLicense();

      if (result.ok) {
        status = result.data;
        failed = false;
      } else if (result.error.kind !== 'unauthenticated') failed = true;

      return result;
    },
    get status(): LicenseStatus | null {
      return status;
    },
  };
};

const license = createLicense();

// A request the server refused for want of a license: look again, and the wall comes up
listenForLicense(() => {
  void license.refresh();
});

export { createLicense, license };
