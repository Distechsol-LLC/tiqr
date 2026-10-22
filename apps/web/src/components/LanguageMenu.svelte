<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import Languages from '@lucide/svelte/icons/languages';
  import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';

  import Flag from '@/components/Flag.svelte';
  import { LOCALES, isLocale } from '@/config/locales.ts';
  import { branding } from '%/useBranding.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';

  type LanguageMenuProps = {
    // A string: Skeleton merges it into its own trigger attributes
    class?: string;
  };

  const { class: className = '' }: LanguageMenuProps = $props();

  const CHECK_SIZE = 16;

  const handleSelect = ({ value }: { value: string }): void => {
    if (isLocale(value)) i18n.set(value);
  };
</script>

{#if branding.locales.length > 1}
  <!-- Sits beside ThemeToggle and matches it; the list opens below, or above near the bottom edge -->
  <Menu onSelect={handleSelect} positioning={{ placement: 'bottom-end' }}>
    <Menu.Trigger
      aria-label={i18n.t.language.label}
      class={`btn-icon btn-icon-2xl text-surface-950-50 hover:preset-tint-primary ${className}`}
      title={i18n.t.language.label}
    >
      <Languages aria-hidden="true" />
    </Menu.Trigger>
    <Portal>
      <Menu.Positioner class="z-30">
        <Menu.Content>
          {#each branding.locales as code (code)}
            <Menu.OptionItem checked={i18n.code === code} type="radio" value={code}>
              <Flag {code} />
              <Menu.ItemText class="flex-1" lang={code}>{LOCALES[code].label}</Menu.ItemText>
              <Menu.ItemIndicator>
                <Check aria-hidden="true" size={CHECK_SIZE} />
              </Menu.ItemIndicator>
            </Menu.OptionItem>
          {/each}
        </Menu.Content>
      </Menu.Positioner>
    </Portal>
  </Menu>
{/if}
