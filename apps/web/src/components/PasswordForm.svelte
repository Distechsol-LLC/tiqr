<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { navigate } from '@/router.ts';
  import { updateUser } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { User } from '$/auth.ts';
  import { passwordResetSchema } from '$/users.ts';

  type PasswordFormProps = {
    user: User | null;
    onClose: () => void;
  };

  const { user, onClose }: PasswordFormProps = $props();

  let password = $state('');
  let confirmation = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(passwordResetSchema.safeParse({ password }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );
  // As `tiqr user password` does, the new password is typed twice
  const confirmationError = $derived(
    isSubmitted && validation.success && confirmation !== password
      ? i18n.t.errors.passwordMismatch
      : undefined
  );

  $effect(() => {
    if (!user) return;

    untrack(() => {
      password = '';
      confirmation = '';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(user && validation.success && confirmation === password && csrfToken)) return;

    isPending = true;

    const result = await updateUser(csrfToken, user.id, validation.data);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.password.notReset, result.error);
      return;
    }

    const isSelf = result.data.id === auth.session?.user.id;

    toaster.success({
      description: isSelf
        ? i18n.t.password.signInAgain
        : i18n.t.password.signedOut(result.data.username),
      title: i18n.t.password.reset,
    });
    onClose();

    // A reset ends the user's sessions, this one included
    if (isSelf) {
      auth.expire();
      await navigate('/login', { replace: true });
    }
  };
</script>

<FormDialog
  isOpen={user !== null}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.password.submit}
  title={i18n.t.password.title(user?.username ?? i18n.t.password.fallback)}
>
  <FloatingInput
    autocomplete="new-password"
    error={fieldErrors.password?.[0]}
    id="reset-password"
    label={i18n.t.password.new}
    required
    type="password"
    bind:value={password}
  />

  <FloatingInput
    autocomplete="new-password"
    error={confirmationError}
    id="reset-password-confirmation"
    label={i18n.t.password.confirm}
    required
    type="password"
    bind:value={confirmation}
  />
</FormDialog>
