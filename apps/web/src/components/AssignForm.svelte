<script lang="ts">
  import { untrack } from 'svelte';

  import FieldError from '@/components/FieldError.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { assignTicket } from '%/api.ts';
  import { ROLE_LABELS } from '%/formatters.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
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
      await notifyFailure('Ticket not assigned', result.error);
      return;
    }

    toaster.success({
      description: `${result.data.readable_serial} → ${validation.data.assignee}`,
      title: 'Ticket assigned',
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
  submitLabel="Assign"
  title={`Assign ${ticket?.readable_serial ?? 'ticket'}`}
>
  {#if ticket}
    <p class="text-surface-600-400">{ticket.visitor_name} · {ticket.visitor_type}</p>
  {/if}

  <label class="label">
    <span class="label-text">Assignee</span>
    <select
      aria-describedby={error ? 'assignee-error' : undefined}
      aria-invalid={error ? 'true' : undefined}
      class="select aria-invalid:ring-error-500"
      required
      bind:value={assignee}
    >
      <option disabled value="">Pick an account</option>
      {#each candidates as account (account.id)}
        <option value={account.username}>{account.username} ({ROLE_LABELS[account.role]})</option>
      {/each}
    </select>
    <FieldError {error} id="assignee-error" />
  </label>
</FormDialog>
