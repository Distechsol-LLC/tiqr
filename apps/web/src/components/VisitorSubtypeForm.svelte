<script lang="ts">
  import { untrack } from 'svelte';
  import { z } from 'zod';

  import FloatingInput from '@/components/FloatingInput.svelte';
  import FormDialog from '@/components/FormDialog.svelte';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { createVisitorSubtype, updateVisitorSubtype } from '%/subtypeApi.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { type VisitorSubtype, type VisitorType, visitorSubtypeInputSchema } from '$/catalog.ts';

  type VisitorSubtypeFormProps = {
    // The type a new subtype goes under, or that the edited one is under
    parent: VisitorType | null;
    // The subtype being changed; null makes a new one
    editing: VisitorSubtype | null;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (subtype: VisitorSubtype) => void;
  };

  const { parent, editing, isOpen, onClose, onSaved }: VisitorSubtypeFormProps = $props();

  // Whole numbers only; the range is checked in the schema
  const DISCOUNT_CHARS = /\D/g;

  let name = $state('');
  let discount = $state('');
  let isPending = $state(false);
  let isSubmitted = $state(false);

  const validation = $derived(visitorSubtypeInputSchema.safeParse({ discount, name }));
  const fieldErrors = $derived(
    isSubmitted && !validation.success ? z.flattenError(validation.error).fieldErrors : {}
  );

  // Each opening starts from the subtype being edited, or blank with no discount
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

    if (!(validation.success && csrfToken && parent)) return;

    const fields = { discount_percent: validation.data.discount, name: validation.data.name };

    isPending = true;

    const result = editing
      ? await updateVisitorSubtype(csrfToken, parent.id, editing.id, fields)
      : await createVisitorSubtype(csrfToken, parent.id, fields);

    isPending = false;

    if (!result.ok) {
      await notifyFailure(
        editing ? i18n.t.visitorSubtypeForm.notUpdated : i18n.t.visitorSubtypeForm.notCreated,
        result.error
      );
      return;
    }

    toaster.success({
      description: result.data.name,
      title: editing ? i18n.t.visitorSubtypeForm.updated : i18n.t.visitorSubtypeForm.created,
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
  title={editing
    ? i18n.t.visitorSubtypeForm.titleEdit
    : i18n.t.visitorSubtypeForm.titleNew(parent?.name ?? '')}
>
  <FloatingInput
    autocomplete="off"
    error={fieldErrors.name?.[0]}
    id="visitor-subtype-name"
    label={i18n.t.visitorSubtypeForm.name}
    required
    bind:value={name}
  />

  <FloatingInput
    autocomplete="off"
    error={fieldErrors.discount?.[0]}
    id="visitor-subtype-discount"
    inputmode="numeric"
    label={i18n.t.visitorSubtypeForm.discount}
    required
    strip={DISCOUNT_CHARS}
    bind:value={discount}
  />
</FormDialog>
