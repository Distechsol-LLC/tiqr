<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { ERROR_PASSWORD_MISMATCH } from '@/config/errors.ts';
  import { navigate } from '@/router.ts';
  import { updateUser } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
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
      ? ERROR_PASSWORD_MISMATCH
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
      await notifyFailure('Password not reset', result.error);
      return;
    }

    const isSelf = result.data.id === auth.session?.user.id;

    toaster.success({
      description: isSelf
        ? 'Sign in with the new password.'
        : `${result.data.username} is signed out everywhere.`,
      title: 'Password reset',
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
  submitLabel="Reset"
  title={`Reset password for ${user?.username ?? 'user'}`}
>
  <FloatingInput
    autocomplete="new-password"
    error={fieldErrors.password?.[0]}
    id="reset-password"
    label="New password"
    required
    type="password"
    bind:value={password}
  />

  <FloatingInput
    autocomplete="new-password"
    error={confirmationError}
    id="reset-password-confirmation"
    label="Confirm password"
    required
    type="password"
    bind:value={confirmation}
  />
</FormDialog>
