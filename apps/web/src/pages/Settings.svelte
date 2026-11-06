<script lang="ts">
  import IdCard from '@lucide/svelte/icons/id-card';
  import TicketIcon from '@lucide/svelte/icons/ticket';
  import { type Component, onMount } from 'svelte';

  import FormDialog from '@/components/FormDialog.svelte';
  import PageHeader from '@/components/PageHeader.svelte';
  import { fetchMode, switchMode } from '%/api.ts';
  import { notifyFailure } from '%/notifyFailure.ts';
  import { toaster } from '%/toaster.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { mode } from '%/useMode.svelte.ts';
  import { type Mode, modeSchema } from '$/settings.ts';

  const ICON_SIZE = 22;
  const MODE_ICONS: Record<Mode, Component> = { badge: IdCard, ticket: TicketIcon };
  const CARDS = modeSchema.options.map((option) => ({ Icon: MODE_ICONS[option], option }));

  const text = $derived(i18n.t.settings);

  let isPinned = $state(false);
  let isLoaded = $state(false);
  // The mode picked here, waiting for the admin to confirm the switch
  let picked = $state<Mode | null>(null);
  let isSwitching = $state(false);

  const load = async (): Promise<void> => {
    const result = await fetchMode();

    if (!result.ok) {
      await notifyFailure(i18n.t.settings.notLoaded, result.error);
      return;
    }

    isPinned = result.data.pinned;
    isLoaded = true;
    mode.set(result.data.mode);
  };

  const close = (): void => {
    picked = null;
  };

  const confirm = async (): Promise<void> => {
    const csrfToken = auth.session?.csrf_token;
    const next = picked;

    if (!(csrfToken && next)) return;

    isSwitching = true;

    const result = await switchMode(csrfToken, next);

    isSwitching = false;

    if (!result.ok) {
      await notifyFailure(i18n.t.settings.notSwitched, result.error);
      return;
    }

    close();
    isPinned = result.data.pinned;
    // Every page reads the mode, so the text, forms and tables follow it from here
    mode.set(result.data.mode);
    toaster.success({
      description: i18n.t.settings.modes[result.data.mode].label,
      title: i18n.t.settings.switched,
    });
  };

  onMount(() => {
    void load();
  });
</script>

<PageHeader description={text.description} title={text.title} />

<div
  class="min-h-0 flex-1 overflow-y-auto bg-[light-dark(white,var(--color-surface-950))] p-4 md:p-8"
>
  <div class="mx-auto max-w-3xl space-y-10">
    <section aria-labelledby="mode-heading" class="flex gap-4">
      <div class="space-y-1">
        <h2 class="h6" id="mode-heading">{text.mode}</h2>
        <p class="text-surface-600-400 text-sm">{text.modeHint}</p>
      </div>

      <!-- One card per mode; picking the other one asks before switching -->
      <div class="grid min-w-96 gap-4 sm:grid-cols-1">
        {#each CARDS as { Icon, option } (option)}
          <button
            aria-pressed={mode.current === option}
            class={[
              'card border-surface-200-800 flex h-full flex-col items-start gap-3 border p-5 text-left transition-colors',
              mode.current === option
                ? 'preset-outlined-primary-500 bg-primary-500/5'
                : 'hover:preset-tint-primary enabled:cursor-pointer',
            ]}
            disabled={!isLoaded || isPinned || mode.current === option}
            onclick={(): void => {
              picked = option;
            }}
            type="button"
          >
            <span class="flex w-full items-center gap-3">
              <span
                class={[
                  'rounded-container grid size-11 shrink-0 place-items-center',
                  mode.current === option ? 'preset-filled-primary-500' : 'preset-tonal',
                ]}
              >
                <Icon aria-hidden="true" size={ICON_SIZE} />
              </span>
              <span class="h6 flex-1">{text.modes[option].label}</span>
              {#if mode.current === option}
                <span class="badge preset-filled-primary-500">{text.current}</span>
              {/if}
            </span>
            <span class="text-surface-700-300 text-sm">{text.modes[option].description}</span>
          </button>
        {/each}
      </div>

      {#if isPinned}
        <p class="text-warning-700-300 text-sm" role="note">{text.pinned}</p>
      {/if}
    </section>
  </div>
</div>

<FormDialog
  isNarrow
  isOpen={picked !== null}
  isPending={isSwitching}
  onClose={close}
  onSubmit={confirm}
  submitLabel={text.switch}
  title={text.switchTitle(picked ? text.modes[picked].label : '')}
>
  <p>{text.switchConfirm}</p>
</FormDialog>
