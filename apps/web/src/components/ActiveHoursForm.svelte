<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FieldError from '@/components/FieldError.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import TimeField from '@/components/TimeField.svelte';
  import { saveActiveHours } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type ActiveHours, activeHoursInputSchema } from '$/operations.ts';

  type ActiveHoursFormProps = {
    // The hours in force now, which the form starts from
    current: ActiveHours;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (hours: ActiveHours) => void;
  };

  const { current, isOpen, onClose, onSaved }: ActiveHoursFormProps = $props();

  let start = $state('');
  let end = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(activeHoursInputSchema.safeParse({ end, start }));

  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Where a fresh limit starts: a working day, until someone picks other times
  const DEFAULT_START = '09:00';
  const DEFAULT_END = '17:00';

  // Each opening starts from the hours in force, so an unsaved change does not carry over
  $effect(() => {
    if (!isOpen) return;

    untrack(() => {
      start = current.start ?? DEFAULT_START;
      end = current.end ?? DEFAULT_END;
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    // Two empty fields lift the limit, so both are sent as null
    const hours = validation.data.start
      ? { end: validation.data.end, start: validation.data.start }
      : { end: null, start: null };

    isPending = true;

    const result = await saveActiveHours(csrfToken, hours);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.activeHours.notSaved, result.error);
      return;
    }

    toaster.success({
      description:
        result.data.start && result.data.end
          ? i18n.t.activeHours.range(result.data.start, result.data.end)
          : i18n.t.activeHours.anyTime,
      title: i18n.t.activeHours.saved,
    });
    onSaved(result.data);
    onClose();
  };
</script>

<FormDialog
  isNarrow
  {isOpen}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={i18n.t.common.save}
  title={i18n.t.activeHours.title}
>
  <div class="flex justify-center-safe gap-4">
    <div class="space-y-1.5">
      <span class="label-text">{i18n.t.activeHours.from}</span>
      <TimeField
        describedBy={fieldErrors.start ? 'active-hours-start' : undefined}
        isInvalid={Boolean(fieldErrors.start)}
        label={i18n.t.activeHours.from}
        bind:value={start}
      />
      <FieldError error={fieldErrors.start?.[0]} id="active-hours-start" />
    </div>

    <div class="space-y-1.5">
      <span class="label-text">{i18n.t.activeHours.to}</span>
      <TimeField
        describedBy={fieldErrors.end ? 'active-hours-end' : undefined}
        isInvalid={Boolean(fieldErrors.end)}
        label={i18n.t.activeHours.to}
        bind:value={end}
      />
      <FieldError error={fieldErrors.end?.[0]} id="active-hours-end" />
    </div>
  </div>
</FormDialog>
