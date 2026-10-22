<script lang="ts">
  import FieldError from '@/components/FieldError.svelte';

  type FloatingSelectProps = {
    id: string;
    label: string;
    options: readonly string[];
    error?: string;
    value?: string;
  };

  let { id, label, options, error, value = $bindable('') }: FloatingSelectProps = $props();

  const errorId = $derived(`${id}-error`);
</script>

<div>
  <div class="relative">
    <!-- Required, so CSS tells an unpicked select (invalid) from a picked one. The empty choice is
         hidden, which keeps it out of the list: until a pick, the label stands in for it -->
    <select
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? 'true' : undefined}
      class="peer select h-12 aria-invalid:ring-error-500"
      {id}
      required
      bind:value
    >
      <option hidden value=""></option>
      {#each options as option (option)}
        <option value={option}>{option}</option>
      {/each}
    </select>
    <!-- Floats onto the top border like FloatingInput's, once focused or picked -->
    <label
      class={[
        'pointer-events-none absolute top-4 left-[calc((var(--text-base)-var(--spacing)*0.5)/2)] origin-left rounded-sm px-1 text-base text-surface-600-400 leading-none',
        'from-surface-50-950 bg-[linear-gradient(transparent_40%,var(--tw-gradient-from)_40%,var(--tw-gradient-from)_56%,transparent_56%)]',
        'dark:bg-surface-950 dark:bg-none',
        'peer-focus:-translate-y-6 peer-focus:scale-75 peer-focus:from-[var(--floating-label-notch,var(--color-surface-100-900))] peer-focus:text-primary-600-400',
        'peer-valid:-translate-y-6 peer-valid:scale-75 peer-valid:from-[var(--floating-label-notch,var(--color-surface-100-900))]',
        'peer-aria-invalid:text-error-600-400',
        'motion-safe:transition-[translate,scale,color,--tw-gradient-from] motion-safe:duration-200 motion-safe:ease-out',
      ]}
      for={id}
    >
      {label}
    </label>
  </div>

  <FieldError {error} id={errorId} />
</div>
