<script lang="ts">
  import KeyRound from '@lucide/svelte/icons/key-round';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import UserCheck from '@lucide/svelte/icons/user-check';
  import UserPlus from '@lucide/svelte/icons/user-plus';
  import UserX from '@lucide/svelte/icons/user-x';
  import { onMount } from 'svelte';

  import DataTable from '@/components/DataTable.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import PasswordForm from '@/components/PasswordForm.svelte';
  import UserForm from '@/components/UserForm.svelte';
  import { fetchUsers, updateUser } from '%/api.ts';
  import { ROLE_LABELS } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { type Role, type User, roleSchema } from '$/auth.ts';
  import type { UserPatch } from '$/users.ts';

  const ICON_SIZE = 18;
  const BASE_COLUMNS = 3;

  // Managers read accounts to pick assignees; only admins change them
  const isAdmin = $derived(auth.session?.user.role === 'admin');
  const selfId = $derived(auth.session?.user.id);
  // The actions column is admin-only
  const columns = $derived(BASE_COLUMNS + (isAdmin ? 1 : 0));

  let users = $state<User[]>([]);
  let isLoading = $state(true);
  let isCreating = $state(false);
  let resetting = $state<User | null>(null);
  let pendingId = $state<string | null>(null);

  // Accounts are never deleted, so the list only grows; keep it alphabetical
  const rows = $derived(users.toSorted((a, b) => a.username.localeCompare(b.username)));

  const load = async (): Promise<void> => {
    isLoading = true;

    const result = await fetchUsers();

    isLoading = false;

    if (result.ok) users = result.data;
    else await notifyFailure('Accounts not loaded', result.error);
  };

  const patch = async (user: User, changes: UserPatch, title: string): Promise<boolean> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken) return false;

    pendingId = user.id;

    const result = await updateUser(csrfToken, user.id, changes);

    pendingId = null;

    if (!result.ok) {
      await notifyFailure(`${title} failed`, result.error);
      return false;
    }

    users = users.map((current) => (current.id === user.id ? result.data : current));
    toaster.success({ description: result.data.username, title });

    return true;
  };

  const changeRole = async (user: User, event: Event): Promise<void> => {
    const select = event.currentTarget as HTMLSelectElement;
    const role = roleSchema.parse(select.value);

    // A refused change puts the old role back on screen
    if (!(await patch(user, { role }, `Role changed to ${ROLE_LABELS[role]}`)))
      select.value = user.role;
  };

  const toggleActive = (user: User): void => {
    void patch(
      user,
      { active: !user.active },
      user.active ? 'User deactivated' : 'User reactivated'
    );
  };

  const closeCreate = (): void => {
    isCreating = false;
  };

  const closeReset = (): void => {
    resetting = null;
  };

  const addUser = (user: User): void => {
    users = [...users, user];
  };

  onMount(() => {
    void load();
  });
</script>

<PageHeader
  description={isAdmin
    ? 'Accounts are never deleted; deactivate them instead.'
    : 'Every account tickets can be assigned to.'}
  title={isAdmin ? 'Users' : 'Accounts'}
>
  {#snippet actions()}
    <button
      aria-label="Refresh"
      class="btn-icon preset-tonal"
      disabled={isLoading}
      onclick={load}
      title="Refresh"
      type="button"
    >
      <RefreshCw
        aria-hidden="true"
        class={isLoading ? 'animate-spin' : undefined}
        size={ICON_SIZE}
      />
    </button>
    {#if isAdmin}
      <button
        class="btn preset-filled-primary-500"
        onclick={(): void => {
          isCreating = true;
        }}
        type="button"
      >
        <UserPlus aria-hidden="true" size={ICON_SIZE} />
        New user
      </button>
    {/if}
  {/snippet}
</PageHeader>

<DataTable
  caption="Accounts"
  {columns}
  emptyMessage="No accounts."
  isEmpty={rows.length === 0}
  {isLoading}
>
  {#snippet head()}
    <th>Username</th>
    <th>Role</th>
    <th>Status</th>
    {#if isAdmin}
      <th><span class="sr-only">Actions</span></th>
    {/if}
  {/snippet}

  {#each rows as user (user.id)}
    <tr class={user.active ? undefined : 'text-surface-600-400'}>
      <td class="font-semibold">
        {user.username}
        {#if user.id === selfId}
          <span class="badge preset-tonal-secondary ml-1">You</span>
        {/if}
      </td>
      <td>
        <!-- Admins can't change their own role; the API refuses it anyway -->
        {#if isAdmin && user.id !== selfId}
          <select
            aria-label={`Role of ${user.username}`}
            class="select w-36 py-1"
            disabled={pendingId === user.id}
            onchange={(event): Promise<void> => changeRole(user, event)}
            value={user.role}
          >
            {#each roleSchema.options as option (option)}
              <option value={option}>{ROLE_LABELS[option as Role]}</option>
            {/each}
          </select>
        {:else}
          {ROLE_LABELS[user.role]}
        {/if}
      </td>
      <td>
        <span class={['badge', user.active ? 'preset-tonal-success' : 'preset-tonal-surface']}>
          {user.active ? 'Active' : 'Deactivated'}
        </span>
      </td>
      {#if isAdmin}
        <td>
          <div class="flex justify-end gap-1">
            <button
              aria-label={`Reset password for ${user.username}`}
              class="btn-icon btn-icon-sm hover:preset-tonal"
              disabled={pendingId === user.id}
              onclick={(): void => {
                resetting = user;
              }}
              title="Reset password"
              type="button"
            >
              <KeyRound aria-hidden="true" size={ICON_SIZE} />
            </button>
            {#if user.id !== selfId}
              <button
                aria-label={`${user.active ? 'Deactivate' : 'Reactivate'} ${user.username}`}
                class={[
                  'btn-icon btn-icon-sm',
                  user.active ? 'hover:preset-tonal-error' : 'hover:preset-tonal-success',
                ]}
                disabled={pendingId === user.id}
                onclick={(): void => toggleActive(user)}
                title={user.active ? 'Deactivate' : 'Reactivate'}
                type="button"
              >
                {#if pendingId === user.id}
                  <LoaderCircle aria-hidden="true" class="animate-spin" size={ICON_SIZE} />
                {:else if user.active}
                  <UserX aria-hidden="true" size={ICON_SIZE} />
                {:else}
                  <UserCheck aria-hidden="true" size={ICON_SIZE} />
                {/if}
              </button>
            {/if}
          </div>
        </td>
      {/if}
    </tr>
  {/each}
</DataTable>

{#if isAdmin}
  <UserForm isOpen={isCreating} onClose={closeCreate} onCreated={addUser} />
  <PasswordForm onClose={closeReset} user={resetting} />
{/if}
