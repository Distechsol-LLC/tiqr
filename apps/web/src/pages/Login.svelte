<script lang="ts">
  import Eye from '@lucide/svelte/icons/eye';
  import EyeOff from '@lucide/svelte/icons/eye-off';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import LogIn from '@lucide/svelte/icons/log-in';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import Logo from '@/components/Logo.svelte';
  import { navigate } from '@/router.ts';
  import { getFailureMessage } from '%/getFailureMessage.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { credentialsSchema } from '$/auth.ts';

  const ICON_SIZE = 18;
  // A fixed id updates the open toast instead of stacking one per attempt
  const SIGN_IN_TOAST = 'sign-in';

  let username = $state('');
  let password = $state('');
  let isPasswordVisible = $state(false);
  let isPending = $state(false);
  let isSubmitted = $state(false);

  let usernameInput = $state<HTMLInputElement>();
  let passwordInput = $state<HTMLInputElement>();

  const validation = $derived(credentialsSchema.safeParse({ password, username }));

  // Errors show after the first submit, then follow the fields as they're corrected
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  const togglePasswordVisibility = (): void => {
    isPasswordVisible = !isPasswordVisible;
  };

  const handleSubmit = async (event: SubmitEvent): Promise<void> => {
    event.preventDefault();

    if (isPending) return;

    isSubmitted = true;

    if (!validation.success) {
      (fieldErrors.username ? usernameInput : passwordInput)?.focus();
      return;
    }

    isPending = true;

    const result = await auth.signIn(validation.data);

    isPending = false;

    if (result.ok) {
      toaster.dismiss(SIGN_IN_TOAST);
      await navigate('/', { replace: true });
      return;
    }

    toaster.error({
      description: getFailureMessage(result.error),
      id: SIGN_IN_TOAST,
      title: 'Sign-in failed',
    });

    if (result.error.kind === 'unauthenticated') {
      password = '';
      isSubmitted = false;
      passwordInput?.focus();
    }
  };
</script>

<svelte:head>
  <title>Sign in · TiQR</title>
</svelte:head>

<main class="grid min-h-dvh place-items-center p-4">
  <div class="w-full max-w-sm space-y-8">
    <header class="flex justify-center-safe items-center-safe gap-4 text-center">
      <Logo class="size-20 shadow-lg" />
      <h1 class="h3">TiQR</h1>
    </header>

    <form
      aria-busy={isPending}
      aria-label="Sign in"
      class="card space-y-5 border border-[light-dark(oklch(0%_0_0/6%),oklch(100%_0_0/6%))] bg-(--card-bg) p-6 shadow-md [--card-bg:light-dark(oklch(99%_0.003_78),color-mix(in_oklab,var(--color-surface-900),var(--color-surface-800)))] [--floating-label-notch:var(--card-bg)]"
      method="post"
      novalidate
      onsubmit={handleSubmit}
    >
      <FloatingInput
        autocapitalize="none"
        autocomplete="username"
        error={fieldErrors.username?.[0]}
        id="username"
        label="Username"
        name="username"
        required
        spellcheck={false}
        bind:input={usernameInput}
        bind:value={username}
      />

      <FloatingInput
        autocomplete="current-password"
        error={fieldErrors.password?.[0]}
        id="password"
        label="Password"
        name="password"
        required
        type={isPasswordVisible ? 'text' : 'password'}
        bind:input={passwordInput}
        bind:value={password}
      >
        {#snippet trailing()}
          <button
            aria-controls="password"
            aria-label={isPasswordVisible ? 'Hide password' : 'Show password'}
            aria-pressed={isPasswordVisible}
            class="btn-icon hover:preset-tonal focus-visible:outline-offset-0"
            onclick={togglePasswordVisibility}
            type="button"
          >
            {#if isPasswordVisible}
              <EyeOff aria-hidden="true" size={ICON_SIZE} />
            {:else}
              <Eye aria-hidden="true" size={ICON_SIZE} />
            {/if}
          </button>
        {/snippet}
      </FloatingInput>

      <button class="btn h-12 w-full preset-filled-primary-500" disabled={isPending} type="submit">
        {#if isPending}
          <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
          Signing in…
        {:else}
          <LogIn aria-hidden="true" size={ICON_SIZE} />
          Sign in
        {/if}
      </button>
    </form>
  </div>
</main>
