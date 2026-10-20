<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createUser } from '%/api.ts';
  import { ROLE_LABELS } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { type Role, type User, roleSchema } from '$/auth.ts';
  import { userInputSchema } from '$/users.ts';

  type UserFormProps = {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (user: User) => void;
  };

  const { isOpen, onClose, onCreated }: UserFormProps = $props();

  let username = $state('');
  let password = $state('');
  let role = $state<Role>('operator');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(userInputSchema.safeParse({ password, role, username }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  $effect(() => {
    if (!isOpen) return;

    untrack(() => {
      username = '';
      password = '';
      role = 'operator';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    isPending = true;

    const result = await createUser(csrfToken, validation.data);

    isPending = false;

    if (!result.ok) {
      await notifyFailure('User not created', result.error);
      return;
    }

    toaster.success({
      description: `${result.data.username} (${ROLE_LABELS[result.data.role]})`,
      title: 'User created',
    });
    onCreated(result.data);
    onClose();
  };
</script>

<FormDialog
  {isOpen}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel="Create"
  title="New user"
>
  <FloatingInput
    autocapitalize="none"
    autocomplete="off"
    error={fieldErrors.username?.[0]}
    id="new-username"
    label="Username"
    required
    spellcheck={false}
    bind:value={username}
  />

  <FloatingInput
    autocomplete="new-password"
    error={fieldErrors.password?.[0]}
    id="new-password"
    label="Password"
    required
    type="password"
    bind:value={password}
  />

  <label class="label">
    <span class="label-text">Role</span>
    <select class="select" bind:value={role}>
      {#each roleSchema.options as option (option)}
        <option value={option}>{ROLE_LABELS[option]}</option>
      {/each}
    </select>
  </label>
</FormDialog>
