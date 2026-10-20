<script lang="ts">
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';

  type FloatingInputProps = Omit<HTMLInputAttributes, 'class' | 'id' | 'placeholder' | 'value'> & {
    id: string;
    label: string;
    error?: string;
    input?: HTMLInputElement;
    trailing?: Snippet;
    value?: string;
  };

  let {
    id,
    label,
    error,
    input = $bindable(),
    trailing,
    value = $bindable(''),
    ...rest
  }: FloatingInputProps = $props();

  const ERROR_ICON_SIZE = 14;

  const errorId = $derived(`${id}-error`);
</script>

<div>
  <div class="relative">
    <!-- A blank placeholder lets CSS tell an empty field from a filled one -->
    <input
      {...rest}
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? 'true' : undefined}
      class={['peer input h-12 aria-invalid:ring-error-500', trailing ? 'pr-12' : undefined]}
      {id}
      placeholder=" "
      bind:this={input}
      bind:value
    />
    <!-- The label starts where Skeleton's .input puts its text, then floats onto the top border.
      Only a thin band across the border is painted, in the parent's color (--floating-label-notch,
      the card by default), so the text itself sits on whatever is behind it, with no two-tone box. -->
    <label
      class={[
        'pointer-events-none absolute top-4 left-[calc((var(--text-base)-var(--spacing)*0.5)/2)] origin-left rounded-sm px-1 text-base text-surface-600-400 leading-none',
        'from-surface-50-950 bg-[linear-gradient(transparent_40%,var(--tw-gradient-from)_40%,var(--tw-gradient-from)_56%,transparent_56%)]',
        'dark:bg-surface-950 dark:bg-none',
        'peer-focus:-translate-y-6 peer-focus:scale-75 peer-focus:from-[var(--floating-label-notch,var(--color-surface-100-900))] peer-focus:text-primary-600-400',
        'peer-not-placeholder-shown:-translate-y-6 peer-not-placeholder-shown:scale-75 peer-not-placeholder-shown:from-[var(--floating-label-notch,var(--color-surface-100-900))]',
        'peer-aria-invalid:text-error-600-400',
        'motion-safe:transition-[translate,scale,color,--tw-gradient-from] motion-safe:duration-200 motion-safe:ease-out',
      ]}
      for={id}
    >
      {label}
    </label>
    {#if trailing}
      <div class="absolute inset-y-0 right-1 flex items-center">
        {@render trailing()}
      </div>
    {/if}
  </div>

  {#if error}
    <p class="mt-1.5 flex items-center gap-1.5 text-error-600-400 text-sm" id={errorId}>
      <CircleAlert aria-hidden="true" class="shrink-0" size={ERROR_ICON_SIZE} />
      {error}
    </p>
  {/if}
</div>
