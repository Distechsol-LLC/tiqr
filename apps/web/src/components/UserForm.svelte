<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createUser } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type Role, type User, roleSchema } from '$/auth.ts';
  import { userInputSchema } from '$/users.ts';

  type UserFormProps = {
    // Admins pick any role; managers only create operators, so they get no choice
    canPickRole: boolean;
    isOpen: boolean;
    onClose: () => void;
    onCreated: (user: User) => void;
  };

  const { canPickRole, isOpen, onClose, onCreated }: UserFormProps = $props();

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
      await notifyFailure(i18n.t.userForm.notCreated, result.error);
      return;
    }

    toaster.success({
      description: `${result.data.username} (${i18n.t.roles[result.data.role]})`,
      title: i18n.t.userForm.created,
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
  submitLabel={i18n.t.common.create}
  title={i18n.t.userForm.title}
>
  <FloatingInput
    autocapitalize="none"
    autocomplete="off"
    error={fieldErrors.username?.[0]}
    id="new-username"
    label={i18n.t.userForm.username}
    required
    spellcheck={false}
    bind:value={username}
  />

  <FloatingInput
    autocomplete="new-password"
    error={fieldErrors.password?.[0]}
    id="new-password"
    label={i18n.t.userForm.password}
    required
    type="password"
    bind:value={password}
  />

  {#if canPickRole}
    <label class="label">
      <span class="label-text text-base">{i18n.t.userForm.role}</span>
      <select class="select h-12" bind:value={role}>
        {#each roleSchema.options as option (option)}
          <option value={option}>{i18n.t.roles[option]}</option>
        {/each}
      </select>
    </label>
  {/if}
</FormDialog>
