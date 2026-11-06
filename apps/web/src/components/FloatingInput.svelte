<script lang="ts">
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import type { Snippet } from 'svelte';
  import type { FormEventHandler, HTMLInputAttributes } from 'svelte/elements';

  type FloatingInputProps = Omit<HTMLInputAttributes, 'class' | 'id' | 'placeholder' | 'value'> & {
    id: string;
    label: string;
    error?: string;
    input?: HTMLInputElement;
    // Matches what is dropped as it is typed or pasted, such as anything but digits
    strip?: RegExp;
    trailing?: Snippet;
    value?: string;
  };

  let {
    id,
    label,
    error,
    input = $bindable(),
    oninput,
    strip,
    trailing,
    value = $bindable(''),
    ...rest
  }: FloatingInputProps = $props();

  const ERROR_ICON_SIZE = 14;

  const errorId = $derived(`${id}-error`);

  const handleInput: FormEventHandler<HTMLInputElement> = (event) => {
    const field = event.currentTarget;

    if (strip) field.value = field.value.replace(strip, '');
    value = field.value;
    oninput?.(event);
  };
</script>

<div>
  <div class="relative">
    <!-- A blank placeholder lets CSS tell an empty field from a filled one -->
    <input
      {...rest}
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? 'true' : undefined}
      class={['peer input aria-invalid:ring-error-500 h-12', trailing ? 'pr-12' : undefined]}
      {id}
      oninput={handleInput}
      placeholder=" "
      {value}
      bind:this={input}
    />
    <!-- The label starts where Skeleton's .input puts its text, then floats onto the top border.
      Once floated, it gets a rounded background in the parent's color (--floating-label-notch,
      the card by default), so the border stops short of the text. At rest it stays transparent. -->
    <label
      class={[
        'text-surface-700-300 pointer-events-none absolute top-4 left-[calc((var(--text-base)-var(--spacing)*0.5)/2)] origin-left rounded-sm bg-transparent px-1 text-base leading-none',
        'peer-focus:text-primary-700-300 peer-focus:-translate-y-6 peer-focus:scale-75 peer-focus:bg-[var(--floating-label-notch,var(--color-surface-100-900))]',
        'peer-not-placeholder-shown:-translate-y-6 peer-not-placeholder-shown:scale-75 peer-not-placeholder-shown:bg-[var(--floating-label-notch,var(--color-surface-100-900))]',
        'peer-aria-invalid:text-error-700-300',
        'motion-safe:transition-[translate,scale,color,background-color] motion-safe:duration-200 motion-safe:ease-out',
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
    <p class="text-error-600-400 mt-1.5 flex items-center gap-1.5 text-sm" id={errorId}>
      <CircleAlert aria-hidden="true" class="shrink-0" size={ERROR_ICON_SIZE} />
      {error}
    </p>
  {/if}
</div>
