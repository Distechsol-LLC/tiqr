<script lang="ts">
  import X from '@lucide/svelte/icons/x';

  import FieldError from '@/components/FieldError.svelte';
  import { i18n } from '%/useLocale.svelte.ts';

  type FloatingSelectProps = {
    id: string;
    label: string;
    options: readonly string[];
    // Shown in place of an option's value, where the value alone reads badly
    labels?: Partial<Record<string, string>>;
    error?: string;
    value?: string;
    // Optional pickers get an X to unpick, and are not required
    clearable?: boolean;
  };

  const ICON_SIZE = 16;

  let {
    id,
    label,
    labels,
    options,
    error,
    clearable = false,
    value = $bindable(''),
  }: FloatingSelectProps = $props();

  const errorId = $derived(`${id}-error`);
  // Picked, not valid: a clearable select is never required, so it is always valid
  const picked = $derived(value !== '');
</script>

<div>
  <div class="relative">
    <!-- Required, so CSS tells an unpicked select (invalid) from a picked one. The empty choice is
         hidden, which keeps it out of the list: until a pick, the label stands in for it -->
    <select
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? 'true' : undefined}
      class="peer select aria-invalid:ring-error-500 h-12 truncate"
      {id}
      required={!clearable}
      bind:value
    >
      <option hidden value=""></option>
      {#each options as option (option)}
        <option value={option}>{labels?.[option] ?? option}</option>
      {/each}
    </select>
    {#if clearable && picked}
      <button
        aria-label={i18n.t.tickets.clearSearch}
        class="btn-icon hover:preset-tint-primary absolute top-1/2 right-9 -translate-y-1/2"
        onclick={(): void => {
          value = '';
        }}
        title={i18n.t.tickets.clearSearch}
        type="button"
      >
        <X aria-hidden="true" size={ICON_SIZE} />
      </button>
    {/if}
    <!-- Floats onto the top border like FloatingInput's, once focused or picked, with the same background -->
    <label
      class={[
        'text-surface-600-400 pointer-events-none absolute top-4 left-[calc((var(--text-base)-var(--spacing)*0.5)/2)] origin-left rounded-sm px-1 text-base leading-none',
        'peer-focus:text-primary-600-400 peer-focus:-translate-y-6 peer-focus:scale-75 peer-focus:bg-[var(--floating-label-notch,var(--color-surface-100-900))]',
        picked
          ? '-translate-y-6 scale-75 bg-[var(--floating-label-notch,var(--color-surface-100-900))]'
          : 'bg-transparent',
        'peer-aria-invalid:text-error-600-400',
        'motion-safe:transition-[translate,scale,color,background-color] motion-safe:duration-200 motion-safe:ease-out',
      ]}
      for={id}
    >
      {label}
    </label>
  </div>

  <FieldError {error} id={errorId} />
</div>
