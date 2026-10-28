<script lang="ts">
  import FieldError from '@/components/FieldError.svelte';

  type FloatingSelectProps = {
    id: string;
    label: string;
    options: readonly string[];
    // Shown in place of an option's value, where the value alone reads badly
    labels?: Partial<Record<string, string>>;
    error?: string;
    value?: string;
  };

  let { id, label, labels, options, error, value = $bindable('') }: FloatingSelectProps = $props();

  const errorId = $derived(`${id}-error`);
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
      required
      bind:value
    >
      <option hidden value=""></option>
      {#each options as option (option)}
        <option value={option}>{labels?.[option] ?? option}</option>
      {/each}
    </select>
    <!-- Floats onto the top border like FloatingInput's, once focused or picked, with the same background -->
    <label
      class={[
        'text-surface-600-400 pointer-events-none absolute top-4 left-[calc((var(--text-base)-var(--spacing)*0.5)/2)] origin-left rounded-sm bg-transparent px-1 text-base leading-none',
        'peer-focus:text-primary-600-400 peer-focus:-translate-y-6 peer-focus:scale-75 peer-focus:bg-[var(--floating-label-notch,var(--color-surface-100-900))]',
        'peer-valid:-translate-y-6 peer-valid:scale-75 peer-valid:bg-[var(--floating-label-notch,var(--color-surface-100-900))]',
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
