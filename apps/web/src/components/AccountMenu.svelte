<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import ChevronsUpDown from '@lucide/svelte/icons/chevrons-up-down';
  import LogOut from '@lucide/svelte/icons/log-out';
  import Moon from '@lucide/svelte/icons/moon';
  import Sun from '@lucide/svelte/icons/sun';
  import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';

  import Flag from '@/components/Flag.svelte';
  import { LOCALES, LOCALE_CODES, isLocale } from '@/config/locales.ts';
  import { navigate } from '@/router.ts';
  import { initialsOf } from '%/initials.ts';
  import { auth } from '%/useAuth.svelte.ts';
  import { i18n } from '%/useLocale.svelte.ts';
  import { theme } from '%/useTheme.svelte.ts';

  type AccountMenuProps = {
    // Full shows the name and role beside the avatar; compact is the avatar alone
    variant: 'full' | 'compact';
    placement: 'top-start' | 'right-end' | 'bottom-end';
    // Full, but with the name faded out, for the collapsed sidebar; the avatar stays put
    isCondensed?: boolean;
  };

  const { variant, placement, isCondensed = false }: AccountMenuProps = $props();

  const ICON_SIZE = 16;
  const THEME_VALUE = 'theme';
  const SIGN_OUT_VALUE = 'sign-out';

  let isPending = $state(false);

  const user = $derived(auth.session?.user);
  const initials = $derived(initialsOf(user?.username ?? '', i18n.code));
  const themeLabel = $derived(theme.mode === 'dark' ? i18n.t.theme.light : i18n.t.theme.dark);

  const handleSignOut = async (): Promise<void> => {
    isPending = true;
    await auth.signOut();
    await navigate('/login', { replace: true });
  };

  const handleSelect = ({ value }: { value: string }): void => {
    if (value === THEME_VALUE) theme.toggle();
    else if (value === SIGN_OUT_VALUE) void handleSignOut();
    else if (isLocale(value)) i18n.set(value);
  };
</script>

{#if user}
  <Menu
    onSelect={handleSelect}
    positioning={{ gutter: 8, placement, sameWidth: variant === 'full' && !isCondensed }}
  >
    <Menu.Trigger
      aria-label={`${i18n.t.nav.account}: ${user.username}`}
      class={variant === 'full'
        ? 'btn w-full justify-start gap-3 p-0.5 text-start hover:preset-tint-primary data-[state=open]:preset-tint-primary'
        : 'btn-icon size-10 rounded-full p-0 hover:ring-2 hover:ring-primary-500/40 data-[state=open]:ring-2 data-[state=open]:ring-primary-500'}
      disabled={isPending}
    >
      <span
        aria-hidden="true"
        class="grid size-9 shrink-0 place-items-center rounded-full bg-primary-500 font-semibold text-primary-contrast-500"
      >
        {initials}
      </span>
      {#if variant === 'full'}
        <span
          class={['min-w-0 flex-1 leading-tight transition-opacity', isCondensed && 'opacity-0']}
        >
          <span class="block truncate font-semibold">{user.username}</span>
          <span class="block truncate text-sm text-surface-600-400">{i18n.t.roles[user.role]}</span>
        </span>
        <ChevronsUpDown
          aria-hidden="true"
          class={['shrink-0 text-surface-600-400 transition-opacity', isCondensed && 'opacity-0']}
          size={ICON_SIZE}
        />
      {/if}
    </Menu.Trigger>
    <Portal>
      <Menu.Positioner class="z-30">
        <Menu.Content class="min-w-56">
          {#if variant === 'compact' || isCondensed}
            <!-- The trigger shows only the avatar here, so name who is signed in -->
            <div class="px-2 py-1 leading-tight">
              <p class="truncate font-semibold">{user.username}</p>
              <p class="text-sm text-surface-600-400">{i18n.t.roles[user.role]}</p>
            </div>
            <Menu.Separator />
          {/if}

          <Menu.ItemGroup aria-label={i18n.t.language.label}>
            {#each LOCALE_CODES as code (code)}
              <Menu.OptionItem checked={i18n.code === code} type="radio" value={code}>
                <Flag {code} />
                <Menu.ItemText class="flex-1" lang={code}>{LOCALES[code].label}</Menu.ItemText>
                <Menu.ItemIndicator class="text-primary-600-400">
                  <Check aria-hidden="true" size={ICON_SIZE} />
                </Menu.ItemIndicator>
              </Menu.OptionItem>
            {/each}
          </Menu.ItemGroup>

          <Menu.Separator />

          <!-- Stays open so the switch can be seen, and undone, in place -->
          <!-- Icon first, in a slot as wide as the flags', so every label above and below starts
               at the same line -->
          <Menu.Item class="justify-start" closeOnSelect={false} value={THEME_VALUE}>
            <span class="me-3 flex w-6 shrink-0 justify-center">
              {#if theme.mode === 'dark'}
                <Sun aria-hidden="true" size={ICON_SIZE} />
              {:else}
                <Moon aria-hidden="true" size={ICON_SIZE} />
              {/if}
            </span>
            <Menu.ItemText class="flex-1 text-start">{themeLabel}</Menu.ItemText>
          </Menu.Item>

          <Menu.Item class="justify-start text-error-700-300" value={SIGN_OUT_VALUE}>
            <span class="me-3 flex w-6 shrink-0 justify-center">
              <LogOut aria-hidden="true" size={ICON_SIZE} />
            </span>
            <Menu.ItemText class="flex-1 text-start">{i18n.t.nav.signOut}</Menu.ItemText>
          </Menu.Item>
        </Menu.Content>
      </Menu.Positioner>
    </Portal>
  </Menu>
{/if}
