<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { createVisitorType, updateVisitorType } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type VisitorType, visitorTypeInputSchema } from '$/catalog.ts';

  type VisitorTypeFormProps = {
    // The type being changed; null makes a new one
    editing: VisitorType | null;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (visitorType: VisitorType) => void;
  };

  const { editing, isOpen, onClose, onSaved }: VisitorTypeFormProps = $props();

  // Whole numbers only; the range is checked in the schema
  const DISCOUNT_CHARS = /\D/g;

  let name = $state('');
  let discount = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(visitorTypeInputSchema.safeParse({ discount, name }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Each opening starts from the type being edited, or blank with no discount
  $effect(() => {
    if (!isOpen) return;

    untrack(() => {
      name = editing?.name ?? '';
      discount = editing ? String(editing.discount_percent) : '';
      isSubmitted = false;
    });
  });

  const handleSubmit = async (): Promise<void> => {
    isSubmitted = true;

    const csrfToken = auth.session?.csrf_token;

    if (!(validation.success && csrfToken)) return;

    const fields = { discount_percent: validation.data.discount, name: validation.data.name };

    isPending = true;

    const result = editing
      ? await updateVisitorType(csrfToken, editing.id, fields)
      : await createVisitorType(csrfToken, fields);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(
        editing ? i18n.t.visitorTypeForm.notUpdated : i18n.t.visitorTypeForm.notCreated,
        result.error
      );
      return;
    }

    toaster.success({
      description: result.data.name,
      title: editing ? i18n.t.visitorTypeForm.updated : i18n.t.visitorTypeForm.created,
    });
    onSaved(result.data);
    onClose();
  };
</script>

<FormDialog
  {isOpen}
  {isPending}
  {onClose}
  onSubmit={handleSubmit}
  submitLabel={editing ? i18n.t.common.save : i18n.t.common.create}
  title={editing ? i18n.t.visitorTypeForm.titleEdit : i18n.t.visitorTypeForm.titleNew}
>
  <FloatingInput
    autocomplete="off"
    error={fieldErrors.name?.[0]}
    id="visitor-type-name"
    label={i18n.t.visitorTypeForm.name}
    required
    bind:value={name}
  />

  <FloatingInput
    autocomplete="off"
    error={fieldErrors.discount?.[0]}
    id="visitor-type-discount"
    inputmode="numeric"
    label={i18n.t.visitorTypeForm.discount}
    required
    strip={DISCOUNT_CHARS}
    bind:value={discount}
  />
</FormDialog>
