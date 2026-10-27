<script lang="ts">
  import KeyRound from '@lucide/svelte/icons/key-round';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import UserCheck from '@lucide/svelte/icons/user-check';
  import UserPlus from '@lucide/svelte/icons/user-plus';
  import UserX from '@lucide/svelte/icons/user-x';
  import UsersRound from '@lucide/svelte/icons/users-round';
  import { onMount } from 'svelte';

  import ActionsHeader from '@/components/ActionsHeader.svelte';
  import DataTable from '@/components/DataTable.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import Pagination from '@/components/Pagination.svelte';
  import PasswordForm from '@/components/PasswordForm.svelte';
  import SortHeader from '@/components/SortHeader.svelte';
  import UserForm from '@/components/UserForm.svelte';
  import { deleteUser, fetchUsers, updateUser } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { pageCount } from '%/pagination.ts';
  import { type SortValues, sortRows } from '%/sort.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { createPagination } from '%/usePagination.svelte.ts';
  import { createSortParams } from '%/useSortParams.svelte.ts';
  import { type Role, type User, roleSchema } from '$/auth.ts';
  import type { UserPatch } from '$/users.ts';

  type SortKey = 'role' | 'status' | 'username';

  type PatchTitles = {
    done: string;
    failed: string;
  };

  const ICON_SIZE = 18;
  const BASE_COLUMNS = 3;
  // Admins reset, toggle and delete; managers only toggle
  const ADMIN_ACTIONS = 3;
  const MANAGER_ACTIONS = 1;

  // Managers read accounts to pick assignees, and add, deactivate and reactivate operators;
  // admins do everything, including role changes, password resets and deletions
  const isAdmin = $derived(auth.session?.user.role === 'admin');
  const isStaff = $derived(isAdmin || auth.session?.user.role === 'manager');
  const selfId = $derived(auth.session?.user.id);
  // The actions column is for staff
  const columns = $derived(BASE_COLUMNS + (isStaff ? 1 : 0));

  const pagination = createPagination();

  let users = $state<User[]>([]);
  let total = $state(0);
  // Counts the requests, so a slow one can't land over a newer one
  let requestId = 0;
  let isLoading = $state(true);
  let isCreating = $state(false);
  let resetting = $state<User | null>(null);
  let deleting = $state<User | null>(null);
  let isDeletePending = $state(false);
  let pendingId = $state<string | null>(null);

  const sortValues: SortValues<User, SortKey> = {
    role: (user) => i18n.t.roles[user.role],
    status: (user) => Number(user.active),
    username: (user) => user.username,
  };

  // Starts by role
  const sorting = createSortParams(sortValues, { direction: 'asc', key: 'role' });

  const rows = $derived(sortRows(users, sorting.sort, sortValues));

  const load = async (): Promise<void> => {
    requestId += 1;

    const id = requestId;

    isLoading = true;

    const result = await fetchUsers({ page: pagination.page, size: pagination.size });

    if (id !== requestId) return;

    if (!result.ok) {
      isLoading = false;
      await notifyFailure(i18n.t.users.notLoaded, result.error);
      return;
    }

    const last = pageCount(result.data.total, pagination.size);

    // A shared link, or deletions, can leave the page past the end: show the last one
    if (pagination.page > last) {
      pagination.goTo(last);
      await load();
      return;
    }

    isLoading = false;
    users = result.data.items;
    total = result.data.total;
  };

  const goToPage = (page: number): void => {
    pagination.goTo(page);
    void load();
  };

  const resize = (size: number): void => {
    pagination.resize(size);
    void load();
  };

  const patch = async (
    user: User,
    changes: UserPatch,
    { done, failed }: PatchTitles
  ): Promise<boolean> => {
    const csrfToken = auth.session?.csrf_token;

    if (!csrfToken) return false;

    pendingId = user.id;

    const result = await updateUser(csrfToken, user.id, changes);

    pendingId = null;

    if (!result.ok) {
      await notifyFailure(failed, result.error);
      return false;
    }

    users = users.map((current) => (current.id === user.id ? result.data : current));
    toaster.success({ description: result.data.username, title: done });

    return true;
  };

  const changeRole = async (user: User, event: Event): Promise<void> => {
    const select = event.currentTarget as HTMLSelectElement;
    const role = roleSchema.parse(select.value);

    const titles = {
      done: i18n.t.users.roleChanged(i18n.t.roles[role]),
      failed: i18n.t.users.roleNotChanged,
    };

    // A refused change puts the old role back on screen
    if (!(await patch(user, { role }, titles))) select.value = user.role;
  };

  const toggleActive = (user: User): void => {
    const { users: text } = i18n.t;

    void patch(
      user,
      { active: !user.active },
      user.active
        ? { done: text.userDeactivated, failed: text.notDeactivated }
        : { done: text.userReactivated, failed: text.notReactivated }
    );
  };

  // Admins act on anyone but themselves; managers only on operators
  const canToggle = (user: User): boolean =>
    user.id !== selfId && (isAdmin || user.role === 'operator');

  const confirmDelete = async (): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;
    const user = deleting;

    if (!(csrfToken && user)) return;

    isDeletePending = true;

    const result = await deleteUser(csrfToken, user.id);

    isDeletePending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.users.notDeleted, result.error);
      return;
    }

    toaster.success({ description: user.username, title: i18n.t.users.userDeleted });
    deleting = null;
    await load();
  };

  const closeDelete = (): void => {
    deleting = null;
  };

  const closeCreate = (): void => {
    isCreating = false;
  };

  const closeReset = (): void => {
    resetting = null;
  };

  // Roles sort the list, so the new account may belong on another page
  const addUser = (): void => {
    void load();
  };

  onMount(() => {
    void load();
  });
</script>

<PageHeader
  description={isAdmin ? i18n.t.users.descriptionAdmin : i18n.t.users.descriptionManager}
  title={isAdmin ? i18n.t.users.titleAdmin : i18n.t.users.titleManager}
>
  {#snippet actions()}
    <button
      aria-label={i18n.t.common.refresh}
      class="btn-icon preset-tonal size-11"
      disabled={isLoading}
      onclick={load}
      title={i18n.t.common.refresh}
      type="button"
    >
      <RefreshCw
        aria-hidden="true"
        class={isLoading ? 'animate-spin' : undefined}
        size={ICON_SIZE}
      />
    </button>
    {#if isStaff}
      <button
        class="btn preset-filled-primary-500 h-11 min-w-36"
        onclick={(): void => {
          isCreating = true;
        }}
        type="button"
      >
        <UserPlus aria-hidden="true" size={ICON_SIZE} />
        {i18n.t.users.new}
      </button>
    {/if}
  {/snippet}
</PageHeader>

<DataTable
  caption={i18n.t.users.caption}
  {columns}
  emptyIcon={UsersRound}
  emptyMessage={i18n.t.users.empty}
  isEmpty={rows.length === 0}
  {isLoading}
  minWidth="40rem"
>
  {#snippet head()}
    <SortHeader
      direction={sorting.directionOf('username')}
      label={i18n.t.users.columns.username}
      onSort={(): void => sorting.sortBy('username')}
    />
    <SortHeader
      class="w-56"
      direction={sorting.directionOf('role')}
      label={i18n.t.users.columns.role}
      onSort={(): void => sorting.sortBy('role')}
    />
    <SortHeader
      class="w-40"
      direction={sorting.directionOf('status')}
      label={i18n.t.users.columns.status}
      onSort={(): void => sorting.sortBy('status')}
    />
    {#if isStaff}
      <ActionsHeader count={isAdmin ? ADMIN_ACTIONS : MANAGER_ACTIONS} />
    {/if}
  {/snippet}

  {#each rows as user (user.id)}
    <tr class={user.active ? undefined : 'text-surface-600-400'}>
      <td class="font-semibold">
        {user.username}
        {#if user.id === selfId}
          <span class="badge border-surface-400-600 text-surface-700-300 ml-1 border"
            >{i18n.t.users.you}</span
          >
        {/if}
      </td>
      <td>
        <!-- Admins can't change their own role; the API refuses it anyway -->
        {#if isAdmin && user.id !== selfId}
          <select
            aria-label={i18n.t.users.roleOf(user.username)}
            class="select h-10 w-full truncate"
            disabled={pendingId === user.id}
            onchange={(event): Promise<void> => changeRole(user, event)}
            value={user.role}
          >
            {#each roleSchema.options as option (option)}
              <option value={option}>{i18n.t.roles[option as Role]}</option>
            {/each}
          </select>
        {:else}
          {i18n.t.roles[user.role]}
        {/if}
      </td>
      <td>
        <!-- Both labels share one grid cell, the other one hidden, so the column is always as wide
             as the longer and never shifts when a status flips -->
        <span class="inline-grid max-w-full grid-cols-1">
          {#each [true, false] as isActive (isActive)}
            <span
              aria-hidden={isActive !== user.active}
              class={[
                'badge-status col-start-1 row-start-1 max-w-full justify-self-start',
                isActive ? 'badge-success' : 'badge-error',
                isActive !== user.active && 'invisible',
              ]}
            >
              <span class="truncate">
                {isActive ? i18n.t.users.active : i18n.t.users.deactivated}
              </span>
            </span>
          {/each}
        </span>
      </td>
      {#if isStaff}
        <td>
          <div class="flex justify-start gap-1">
            {#if isAdmin}
              <button
                aria-label={i18n.t.users.resetPasswordFor(user.username)}
                class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-primary"
                disabled={pendingId === user.id}
                onclick={(): void => {
                  resetting = user;
                }}
                title={i18n.t.users.resetPassword}
                type="button"
              >
                <KeyRound aria-hidden="true" size={ICON_SIZE} />
              </button>
            {/if}
            {#if canToggle(user)}
              <button
                aria-label={user.active
                  ? i18n.t.users.deactivateUser(user.username)
                  : i18n.t.users.reactivateUser(user.username)}
                class={[
                  'btn-icon btn-icon-lg text-surface-950-50',
                  user.active ? 'hover:preset-tint-error' : 'hover:preset-tint-success',
                ]}
                disabled={pendingId === user.id}
                onclick={(): void => toggleActive(user)}
                title={i18n.t.users.toggleStatus}
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
            <!-- Deleting is a second step, offered once an account is deactivated -->
            {#if isAdmin && !user.active && user.id !== selfId}
              <button
                aria-label={i18n.t.users.deleteUser(user.username)}
                class="btn-icon btn-icon-lg text-surface-950-50 hover:preset-tint-error"
                disabled={pendingId === user.id}
                onclick={(): void => {
                  deleting = user;
                }}
                title={i18n.t.users.delete}
                type="button"
              >
                <Trash2 aria-hidden="true" size={ICON_SIZE} />
              </button>
            {/if}
          </div>
        </td>
      {/if}
    </tr>
  {/each}
</DataTable>

<Pagination
  {isLoading}
  onPage={goToPage}
  onSize={resize}
  page={pagination.page}
  size={pagination.size}
  {total}
/>

{#if isStaff}
  <UserForm canPickRole={isAdmin} isOpen={isCreating} onClose={closeCreate} onCreated={addUser} />
{/if}
{#if isAdmin}
  <PasswordForm onClose={closeReset} user={resetting} />
  <FormDialog
    isDestructive
    isOpen={deleting !== null}
    isPending={isDeletePending}
    onClose={closeDelete}
    onSubmit={confirmDelete}
    submitLabel={i18n.t.users.delete}
    title={i18n.t.users.deleteTitle}
  >
    <p>{deleting ? i18n.t.users.deleteConfirm(deleting.username) : ''}</p>
  </FormDialog>
{/if}
