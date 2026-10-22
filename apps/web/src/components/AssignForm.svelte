<script lang="ts">
  import { untrack } from 'svelte';

  import FieldError from '@/components/FieldError.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { assignTicket } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import type { User } from '$/auth.ts';
  import { type Ticket, assignInputSchema } from '$/tickets.ts';

  type AssignFormProps = {
    ticket: Ticket | null;
    accounts: User[];
    onClose: () => void;
    onAssigned: (ticket: Ticket) => void;
  };

  const { ticket, accounts, onClose, onAssigned }: AssignFormProps = $props();

  let assignee = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  // Deactivated accounts can't take tickets
  const candidates = $derived(accounts.filter((account) => account.active));
  const validation = $derived(assignInputSchema.safeParse({ assignee }));
  const error = $derived(
    isSubmitted && !validation.success ? validation.error.issues[0]?.message : undefined
  );

  // Starts on the current assignee, if they can still be picked
  $effect(() => {
    if (!ticket) return;

    const { assigned_operator } = ticket;

    untrack(() => {
      assignee = candidates.find((account) => account.id === assigned_operator)?.username ?? '';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(ticket && validation.success && csrfToken)) return;

    isPending = true;

    const result = await assignTicket(csrfToken, ticket.id, validation.data);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.assign.notAssigned, result.error);
      return;
    }

    toaster.success({
      description: `${result.data.readable_serial} → ${validation.data.assignee}`,
      title: i18n.t.assign.assigned,
    });
    onAssigned(result.data);
    onClose();
  };
</script>

<FormDialog
  isOpen={ticket !== null}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.assign.submit}
  title={i18n.t.assign.title(ticket?.readable_serial ?? i18n.t.assign.fallback)}
>
  {#if ticket}
    <p class="text-surface-600-400">{ticket.visitor_name} · {ticket.visitor_type}</p>
  {/if}

  <label class="label">
    <span class="label-text text-base">{i18n.t.assign.assignee}</span>
    <select
      aria-describedby={error ? 'assignee-error' : undefined}
      aria-invalid={error ? 'true' : undefined}
      class="select h-12 aria-invalid:ring-error-500"
      required
      bind:value={assignee}
    >
      <option disabled value="">{i18n.t.assign.pick}</option>
      {#each candidates as account (account.id)}
        <option value={account.username}>{account.username} ({i18n.t.roles[account.role]})</option>
      {/each}
    </select>
    <FieldError {error} id="assignee-error" />
  </label>
</FormDialog>
