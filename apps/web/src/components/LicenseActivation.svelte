<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import Copy from '@lucide/svelte/icons/copy';
  import KeyRound from '@lucide/svelte/icons/key-round';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import { untrack } from 'svelte';

  import { activateLicense, fetchRequestCode } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { license } from '%/useLicense.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type RequestType, requestTypeSchema } from '$/license.ts';

  type LicenseActivationProps = {
    // Anyone can request a code; only an admin can activate a key
    canActivate: boolean;
  };

  const { canActivate }: LicenseActivationProps = $props();

  const ICON_SIZE = 18;
  const COPIED_FOR = 2000;
  const REQUEST_TYPES = requestTypeSchema.options;

  let requestType = $state<RequestType>('standard');
  let code = $state('');
  let key = $state('');
  let isRequesting = $state(false);
  let isActivating = $state(false);
  let isCopied = $state(false);
  let refusal = $state('');
  // Counts the requests, so a slow code can't land over a newer choice
  let requestId = 0;

  const typeLabel = (type: RequestType): string =>
    type === 'trial' ? i18n.t.license.requestTrial : i18n.t.license.requestStandard;

  // The server's codes, in the showing language; anything else falls back to its own message
  const refusalMessage = (serverCode: string | null, detail: string | null): string => {
    const { license: text } = i18n.t;

    switch (serverCode) {
      case 'license_bad_signature':
        return text.badSignature;
      case 'license_wrong_machine':
        return detail ?? text.wrongMachine;
      case 'license_already_expired':
        return text.alreadyExpired;
      case 'license_trial_over_paid':
        return text.trialOverPaid;
      default:
        return detail ?? i18n.t.errors.server;
    }
  };

  const loadCode = async (type: RequestType): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isRequesting = true;

    const result = await fetchRequestCode(type);

    if (id !== requestId) return;

    isRequesting = false;

    if (!result.ok) {
      code = '';
      await notifyFailure(i18n.t.license.codeFailed, result.error);
      return;
    }

    code = result.data;
  };

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(code);
      isCopied = true;
      setTimeout(() => {
        isCopied = false;
      }, COPIED_FOR);
    } catch {
      // Clipboard access can be refused; the code stays selectable on screen
    }
  };

  const activate = async (event: SubmitEvent): Promise<void> => {
    event.preventDefault();

    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken || isActivating || !key.trim()) return;

    isActivating = true;
    refusal = '';

    const result = await activateLicense(csrfToken, key.trim());

    isActivating = false;

    if (!result.ok) {
      if (result.error.kind === 'server')
        refusal = refusalMessage(result.error.code, result.error.detail);
      else await notifyFailure(i18n.t.license.activate, result.error);

      return;
    }

    key = '';
    toaster.success({ title: i18n.t.license.activated });
    await license.refresh();
  };

  $effect(() => {
    const type = requestType;

    untrack(() => {
      void loadCode(type);
    });
  });
</script>

<section class="space-y-3">
  <h2 class="h6">{i18n.t.license.requestCode}</h2>
  <p class="text-sm text-surface-600-400">{i18n.t.license.requestHint}</p>

  <fieldset class="flex flex-wrap gap-4">
    <legend class="sr-only">{i18n.t.license.requestType}</legend>
    {#each REQUEST_TYPES as type (type)}
      <label class="flex items-center gap-2">
        <input
          class="radio"
          name="request-type"
          type="radio"
          value={type}
          bind:group={requestType}
        />
        <span>{typeLabel(type)}</span>
      </label>
    {/each}
  </fieldset>

  <div class="flex items-start gap-2">
    <p
      class="min-h-12 flex-1 rounded-container bg-surface-100-900 p-3 font-mono text-xs break-all select-all"
      data-testid="request-code"
    >
      {code}
    </p>
    <button
      aria-label={i18n.t.license.copy}
      class="btn-icon size-12 preset-tonal"
      disabled={!code || isRequesting}
      onclick={copy}
      title={isCopied ? i18n.t.license.copied : i18n.t.license.copy}
      type="button"
    >
      {#if isRequesting}
        <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
      {:else if isCopied}
        <Check aria-hidden="true" size={ICON_SIZE} />
      {:else}
        <Copy aria-hidden="true" size={ICON_SIZE} />
      {/if}
    </button>
  </div>
</section>

<section class="space-y-3">
  {#if canActivate}
    <form class="space-y-3" onsubmit={activate}>
      <label class="block">
        <span class="h6">{i18n.t.license.keyLabel}</span>
        <textarea
          class="textarea mt-2 font-mono text-xs"
          placeholder={i18n.t.license.keyPlaceholder}
          rows="5"
          spellcheck="false"
          bind:value={key}
        ></textarea>
      </label>
      {#if refusal}
        <p class="text-error-600-400 text-sm" role="alert">{refusal}</p>
      {/if}
      <button
        class="btn h-12 w-full preset-filled-primary-500"
        disabled={isActivating || !key.trim()}
        type="submit"
      >
        {#if isActivating}
          <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
        {:else}
          <KeyRound aria-hidden="true" size={ICON_SIZE} />
        {/if}
        {i18n.t.license.activate}
      </button>
    </form>
  {:else}
    <p class="text-sm text-surface-600-400">{i18n.t.license.notAdmin}</p>
  {/if}
</section>
